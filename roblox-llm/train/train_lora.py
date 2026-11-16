"""First real run: LoRA fine-tune of Qwen3.5-4B on the clean Roblox/Luau dataset (text only).

Budget-bound by design: a fixed token budget (TOKEN_BUDGET), a hard wall-clock cap (MAX_HOURS), and a
held-out eval set taken before training. Output: a LoRA adapter plus eval_report.json on the rbx-models
Volume, so the base model and the adapter can be compared on the same held-out data.

    modal run --detach train/train_lora.py --run-name v1
"""
from __future__ import annotations

import json
import math
import random
import time

import modal

APP = "rbx-train"
app = modal.App(APP)
data_vol = modal.Volume.from_name("rbx-crawl")
model_vol = modal.Volume.from_name("rbx-models", create_if_missing=True)
MODEL_ID = "Qwen/Qwen3.5-4B"
MODELS = "/models"
CLEAN = "/data/clean"

TOKEN_BUDGET = 40_000_000       # training tokens (about 1.6 h on H100 at ~7k tok/s)
SEQ_LEN = 2048
BATCH = 4                       # sequences per optimizer step  -> 8192 tokens/step
EVAL_SEQS = 160                 # held-out sequences, per kind, excluded from training
MAX_HOURS = 2.25                # hard wall-clock cap for the training loop
LR = 2e-4
# Mix by target share of TOKENS (roughly matches the clean dataset's content).
MIX = {"code": 0.35, "instruct": 0.25, "doc": 0.20, "qa": 0.10, "chat": 0.10}
KIND_MAP = {"code": "code", "instruct": "instruct", "doc": "doc", "api": "doc", "qa": "qa", "chat": "chat"}

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch>=2.11", "triton>=3.7.1", "transformers==5.23.0", "peft==0.21.3", "accelerate>=1.2",
        "datasets>=3.0", "zstandard>=0.22", "huggingface_hub>=0.30", "flash-linear-attention",
    )
    .env({"HF_HOME": f"{MODELS}/hf-cache"})
)


def _iter_clean_records(clean_dir: str, seed: int):
    import glob
    import io
    import zstandard as zstd

    shards = sorted(glob.glob(f"{clean_dir}/*.jsonl.zst"))
    random.Random(seed).shuffle(shards)           # mix sources instead of reading one shard at a time
    for path in shards:
        with open(path, "rb") as fh:
            reader = io.TextIOWrapper(zstd.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
            for line in reader:
                yield json.loads(line)


def _collect(tok, quotas: dict[str, int], seed: int):
    """Tokenize records until each kind has its quota of tokens. Returns {kind: [token lists]}."""
    got = {k: [] for k in quotas}
    filled = {k: 0 for k in quotas}
    for rec in _iter_clean_records(CLEAN, seed):
        kind = KIND_MAP.get(rec.get("kind"))
        if kind is None or filled.get(kind, 0) >= quotas.get(kind, 0):
            continue
        if (rec.get("flags") or {}).get("quality", 1.0) < 0.3:   # skip the weakest quality tier
            continue
        ids = tok(rec["text"], add_special_tokens=False)["input_ids"] + [tok.eos_token_id]
        got[kind].append(ids)
        filled[kind] += len(ids)
        if all(filled[k] >= quotas[k] for k in quotas):
            break
    return got, filled


def _pack(docs: list[list[int]], seq_len: int) -> list[list[int]]:
    stream: list[int] = []
    for d in docs:
        stream += d
    return [stream[i:i + seq_len] for i in range(0, len(stream) - seq_len + 1, seq_len)]


@app.function(image=image, gpu="H100", memory=32768, volumes={"/data": data_vol, MODELS: model_vol}, timeout=4 * 3600)
def train(run_name: str = "v1", token_budget: int = TOKEN_BUDGET, seed: int = 1234) -> dict:
    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    t_start = time.time()
    report: dict = {"run": run_name, "token_budget": token_budget, "mix": MIX}
    tok = AutoTokenizer.from_pretrained(MODEL_ID, cache_dir=f"{MODELS}/hf-cache")
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID, dtype=torch.bfloat16, cache_dir=f"{MODELS}/hf-cache", device_map="cuda")

    # ---- data: per-kind token quotas, plus held-out eval sequences per kind (never trained on)
    quotas = {k: int(token_budget * share) for k, share in MIX.items()}
    eval_quota = {k: EVAL_SEQS * SEQ_LEN for k in MIX}
    got, filled = _collect(tok, {k: quotas[k] + eval_quota[k] for k in quotas}, seed)
    eval_seqs: dict[str, list[list[int]]] = {}
    train_docs: list[list[int]] = []
    for k in quotas:
        docs = got[k]
        eval_docs = docs[: max(1, len(docs) // 10)]          # first 10% of each kind's docs -> eval pool
        eval_seqs[k] = _pack(eval_docs, SEQ_LEN)[:EVAL_SEQS]
        train_docs += docs[len(eval_docs):]
    random.Random(seed).shuffle(train_docs)
    train_seqs = _pack(train_docs, SEQ_LEN)
    random.Random(seed + 1).shuffle(train_seqs)
    report["train_seqs"] = len(train_seqs)
    report["train_tokens"] = len(train_seqs) * SEQ_LEN
    report["eval_seqs_per_kind"] = {k: len(v) for k, v in eval_seqs.items()}

    def eval_loss(m) -> dict:
        m.eval()
        out = {}
        with torch.no_grad():
            for k, seqs in eval_seqs.items():
                tot, n = 0.0, 0
                for i in range(0, len(seqs), BATCH):
                    x = torch.tensor(seqs[i:i + BATCH], device="cuda")
                    tot += m(input_ids=x, labels=x).loss.item() * x.shape[0]
                    n += x.shape[0]
                out[k] = round(tot / max(1, n), 4)
        m.train()
        return out

    # ---- baseline on the held-out data, before any training
    report["eval_base"] = eval_loss(model)

    # ---- LoRA
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    cfg = LoraConfig(r=32, lora_alpha=64, lora_dropout=0.05, task_type="CAUSAL_LM",
                     target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(model, cfg)
    model.train()
    params = [p for p in model.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=LR, weight_decay=0.0)
    steps = len(train_seqs) // BATCH
    warm = max(20, steps // 50)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / warm) * 0.5 * (1 + math.cos(math.pi * min(1.0, s / steps))))
    report["steps"] = steps

    log = []
    t_train = time.time()
    run_out = f"{MODELS}/runs/{run_name}"
    for s in range(steps):
        if (time.time() - t_start) / 3600 > MAX_HOURS:
            report["stopped_early"] = f"wall-clock cap {MAX_HOURS} h reached at step {s}"
            break
        x = torch.tensor(train_seqs[s * BATCH:(s + 1) * BATCH], device="cuda")
        loss = model(input_ids=x, labels=x).loss
        loss.backward()
        torch.nn.utils.clip_grad_norm_(params, 1.0)
        opt.step()
        sched.step()
        opt.zero_grad(set_to_none=True)
        if s % 50 == 0 or s == steps - 1:
            el = time.time() - t_train
            tps = (s + 1) * BATCH * SEQ_LEN / max(el, 1e-6)
            log.append({"step": s, "loss": round(loss.item(), 4), "tok_per_s": round(tps), "elapsed_min": round(el / 60, 1)})
            print(log[-1], flush=True)
        if s and s % 1000 == 0:
            model.save_pretrained(f"{run_out}/step{s}")
            model_vol.commit()
    model.save_pretrained(run_out)
    model_vol.commit()
    report["train_log"] = log
    report["train_minutes"] = round((time.time() - t_train) / 60, 1)

    # ---- eval after training, same held-out sequences
    report["eval_after"] = eval_loss(model)
    report["improvement"] = {k: round(report["eval_base"][k] - report["eval_after"][k], 4) for k in report["eval_base"]}
    report["total_minutes"] = round((time.time() - t_start) / 60, 1)
    with open(f"{run_out}/eval_report.json", "w") as fh:
        json.dump(report, fh, indent=1)
    model_vol.commit()
    return report


@app.local_entrypoint()
def main(run_name: str = "v1", token_budget: int = TOKEN_BUDGET):
    print(json.dumps(train.remote(run_name, token_budget), indent=1))

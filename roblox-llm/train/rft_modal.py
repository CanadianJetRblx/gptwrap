"""Measure and improve with rejection sampling (RFT) on Modal GPUs.

Stages (each spawned, so a disconnected client cannot cancel it):
  gen    eval:   greedy answers for ALL held-out tasks (nothing dropped, so every model is scored on the same set)
         sample: k answers per TRAINING debugging task (repositories disjoint from the held-out set)
  train  LoRA fine-tune on verifier-passing answers, starting from the v1 adapter

    modal run train/rft_modal.py --stage gen --model base --name eval_base
    modal run train/rft_modal.py --stage gen --model v1 --name eval_v1
    modal run train/rft_modal.py --stage gen --model v1 --name rft_samples --sample-train 400 --k 4
    modal run train/rft_modal.py --stage train --run-name rft1 --data-name rft_train

Outputs land on the rbx-models Volume under eval/ and runs/. Scoring is done locally with
dataset_v2/eval_harness.py (eval) and train/rft_select.py (samples) so every model is judged by the same verifier.
"""
from __future__ import annotations

import json
import random

import modal

app = modal.App("rbx-rft")
data_vol = modal.Volume.from_name("rbx-crawl")
model_vol = modal.Volume.from_name("rbx-models", create_if_missing=True)
MODEL_ID = "Qwen/Qwen3.5-4B"
MODELS = "/models"
DATA = "/data"
ADAPTERS = {"v1": "runs/v1", "rft": "runs/rft1", "chat": "runs/chat1"}

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch>=2.11", "triton>=3.7.1", "transformers==5.23.0", "peft==0.21.3", "accelerate>=1.2",
        "datasets>=3.0", "zstandard>=0.22", "huggingface_hub>=0.30", "flash-linear-attention",
    )
    .env({"HF_HOME": f"{MODELS}/hf-cache"})
)

MAX_TRAIN_PROMPT_CHARS = 8000   # training samples only; eval keeps every task


def _load(model_kind: str):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(MODEL_ID, cache_dir=f"{MODELS}/hf-cache")
    tok.padding_side = "left"
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, dtype=torch.bfloat16,
                                                 cache_dir=f"{MODELS}/hf-cache", device_map="cuda")
    if model_kind in ADAPTERS:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, f"{MODELS}/{ADAPTERS[model_kind]}")
    model.eval()
    return tok, model


def _chat(tok, prompt: str) -> str:
    return tok.apply_chat_template([{"role": "user", "content": prompt}], tokenize=False,
                                   add_generation_prompt=True, enable_thinking=False)


@app.function(image=image, gpu="H100", memory=32768, volumes={DATA: data_vol, MODELS: model_vol}, timeout=3 * 3600)
def gen(model_kind: str, name: str, sample_train: int = 0, k: int = 1, max_new_tokens: int = 2048,
        temperature: float = 0.8, seed: int = 13, limit: int = 0, max_seqs: int = 32,
        max_prompt_tokens: int = 48000) -> dict:
    import io
    import os
    import time
    import torch
    import zstandard as zstd

    t0 = time.time()
    if sample_train:
        rows = []
        with open(f"{DATA}/dataset_v2/final/sft_train.jsonl.zst", "rb") as fh:
            reader = io.TextIOWrapper(zstd.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
            for line in reader:
                r = json.loads(line)
                if r.get("task_type") == "debug_detected_fault" and len(r["messages"][0]["content"]) <= MAX_TRAIN_PROMPT_CHARS:
                    rows.append(r)
        random.Random(seed).shuffle(rows)
        tasks = [{"task_id": f"s{i}", "prompt": r["messages"][0]["content"], "path": r["path"],
                  "reference": r["messages"][1]["content"]} for i, r in enumerate(rows[:sample_train])]
        samples, temp = k, temperature
    else:
        tasks = [json.loads(l) for l in open(f"{DATA}/dataset_v2/final/eval_tasks.jsonl")]
        if limit:
            tasks = tasks[:limit]      # file order; the same subset is scored for every model
        samples, temp = 1, 0.0

    tok, model = _load(model_kind)
    eos_ids = {i for i in (tok.convert_tokens_to_ids("<|im_end|>"), tok.convert_tokens_to_ids("<|endoftext|>"),
                           tok.eos_token_id, tok.pad_token_id) if i is not None}
    texts = [_chat(tok, t["prompt"]) for t in tasks]
    lens = [len(tok(x, add_special_tokens=False)["input_ids"]) for x in texts]

    # token-budget batches: short prompts batch together, long files run alone
    order = sorted(range(len(tasks)), key=lambda i: lens[i])
    batches, cur = [], []
    for i in order:
        if cur and ((len(cur) + 1) * samples > max_seqs or (len(cur) + 1) * samples * lens[i] > max_prompt_tokens):
            batches.append(cur)
            cur = []
        cur.append(i)
    if cur:
        batches.append(cur)

    out: dict[str, list[str]] = {}
    truncated = 0
    errors: list[str] = []
    for bi, idx in enumerate(batches):
        enc = tok([texts[i] for i in idx], return_tensors="pt", padding=True, add_special_tokens=False).to("cuda")
        kwargs = dict(max_new_tokens=max_new_tokens, pad_token_id=tok.pad_token_id, num_return_sequences=samples)
        if temp > 0:
            kwargs.update(do_sample=True, temperature=temp, top_p=0.95)
        else:
            kwargs.update(do_sample=False)
        try:
            with torch.no_grad():
                gen_ids = model.generate(**enc, **kwargs)
        except torch.OutOfMemoryError:
            torch.cuda.empty_cache()
            errors += [tasks[i]["task_id"] for i in idx]
            for i in idx:
                out[tasks[i]["task_id"]] = [""] * samples
            print(f"batch {bi}: OOM, {len(idx)} tasks scored as failures", flush=True)
            continue
        n_in = enc["input_ids"].shape[1]
        new = gen_ids[:, n_in:]
        decoded = tok.batch_decode(new, skip_special_tokens=True)
        for j, i in enumerate(idx):
            outs = []
            for s in range(samples):
                r = j * samples + s
                if not any(int(x) in eos_ids for x in new[r].tolist()):
                    truncated += 1          # hit max_new_tokens before finishing
                outs.append(decoded[r])
            out[tasks[i]["task_id"]] = outs
        print(f"batch {bi + 1}/{len(batches)}: {len(out)}/{len(tasks)} tasks, {time.time() - t0:.0f}s", flush=True)

    res = {"name": name, "model": model_kind, "k": samples, "temperature": temp, "max_new_tokens": max_new_tokens,
           "truncated_generations": truncated, "oom_tasks": errors,
           "tasks": [{k2: t[k2] for k2 in ("task_id", "path", "reference", "prompt") if k2 in t} for t in tasks],
           "outputs": out, "seconds": round(time.time() - t0)}
    os.makedirs(f"{MODELS}/eval", exist_ok=True)
    with open(f"{MODELS}/eval/{name}.json", "w") as fh:
        json.dump(res, fh)
    model_vol.commit()
    return {"name": name, "tasks": len(tasks), "truncated": truncated, "oom_tasks": len(errors),
            "seconds": res["seconds"]}


@app.function(image=image, gpu="H100", memory=32768, volumes={DATA: data_vol, MODELS: model_vol}, timeout=2 * 3600)
def train(run_name: str = "rft1", data_name: str = "rft_train", lr: float = 5e-5,
          batch: int = 2, accum: int = 4) -> dict:
    import time
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    t0 = time.time()
    rows = [json.loads(l) for l in open(f"{MODELS}/runs/{data_name}.jsonl")]
    tok = AutoTokenizer.from_pretrained(MODEL_ID, cache_dir=f"{MODELS}/hf-cache")
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, dtype=torch.bfloat16,
                                                 cache_dir=f"{MODELS}/hf-cache", device_map="cuda")
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model = PeftModel.from_pretrained(model, f"{MODELS}/runs/v1", is_trainable=True)   # continue from v1
    model.train()

    eos = tok.convert_tokens_to_ids("<|im_end|>") or tok.eos_token_id
    examples = []
    for r in rows:
        prompt = tok.apply_chat_template([r["messages"][0]], tokenize=False, add_generation_prompt=True,
                                         enable_thinking=False)
        p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
        a_ids = tok(r["messages"][1]["content"], add_special_tokens=False)["input_ids"] + [eos]
        ids = (p_ids + a_ids)[:4096]
        labels = ([-100] * len(p_ids) + a_ids)[:4096]
        examples.append((ids, labels))
    random.Random(7).shuffle(examples)

    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)
    steps, log = 0, []
    n_micro = 0
    for s in range(0, len(examples), batch):
        chunk = examples[s:s + batch]
        L = max(len(x[0]) for x in chunk)
        ids = torch.tensor([x[0] + [tok.pad_token_id] * (L - len(x[0])) for x in chunk], device="cuda")
        lab = torch.tensor([x[1] + [-100] * (L - len(x[1])) for x in chunk], device="cuda")
        att = torch.tensor([[1] * len(x[0]) + [0] * (L - len(x[0])) for x in chunk], device="cuda")
        loss = model(input_ids=ids, attention_mask=att, labels=lab).loss / accum
        loss.backward()
        n_micro += 1
        if n_micro % accum == 0:
            opt.step()
            opt.zero_grad(set_to_none=True)
            steps += 1
            if steps % 10 == 0:
                log.append({"step": steps, "loss": round(loss.item() * accum, 4)})
                print(log[-1], flush=True)
    if n_micro % accum:
        opt.step()
        steps += 1
    model.save_pretrained(f"{MODELS}/runs/{run_name}")
    model_vol.commit()
    return {"run": run_name, "examples": len(examples), "optimizer_steps": steps, "log": log,
            "minutes": round((time.time() - t0) / 60, 1)}


@app.function(image=image, gpu="H100", memory=32768, volumes={DATA: data_vol, MODELS: model_vol}, timeout=2 * 3600)
def chat_sft(run_name: str = "chat1", n_debug: int = 1500, n_header: int = 1500, max_minutes: float = 20.0,
             lr: float = 2e-4, max_len: int = 2048, seed: int = 21) -> dict:
    """Chat-format SFT from the BASE model. The v1 adapter learned to continue text and never ends its turn,
    so this run trains on the v2 instruction pairs in exactly the evaluation format, with the end-of-turn
    token as the last target. Wall-clock capped (max_minutes) to bound the cost; the adapter is saved either way."""
    import io
    import time
    import torch
    import zstandard as zstd
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer

    t0 = time.time()
    rng = random.Random(seed)
    debug_rows, header_rows = [], []
    with open(f"{DATA}/dataset_v2/final/sft_train.jsonl.zst", "rb") as fh:
        reader = io.TextIOWrapper(zstd.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
        for line in reader:
            r = json.loads(line)
            if r.get("task_type") == "debug_detected_fault":
                if rng.random() < 0.1:
                    debug_rows.append(r)
            elif rng.random() < 0.03:
                header_rows.append(r)
    rng.shuffle(debug_rows)
    rng.shuffle(header_rows)

    tok = AutoTokenizer.from_pretrained(MODEL_ID, cache_dir=f"{MODELS}/hf-cache")
    eos = tok.convert_tokens_to_ids("<|im_end|>")

    def encode(r):
        prompt = tok.apply_chat_template([r["messages"][0]], tokenize=False, add_generation_prompt=True,
                                         enable_thinking=False)
        p = tok(prompt, add_special_tokens=False)["input_ids"]
        a = tok(r["messages"][1]["content"], add_special_tokens=False)["input_ids"] + [eos]
        if len(p) + len(a) > max_len:
            return None
        return p + a, [-100] * len(p) + a

    def take(rows, n):
        out = []
        for r in rows:
            e = encode(r)
            if e:
                out.append(e)
            if len(out) >= n:
                break
        return out

    examples = take(debug_rows, n_debug) + take(header_rows, n_header)
    random.Random(seed + 1).shuffle(examples)
    print(f"examples: {len(examples)} (debug target {n_debug}, header target {n_header})", flush=True)

    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, dtype=torch.bfloat16,
                                                 cache_dir=f"{MODELS}/hf-cache", device_map="cuda")
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    cfg = LoraConfig(r=32, lora_alpha=64, lora_dropout=0.05, task_type="CAUSAL_LM",
                     target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(model, cfg)
    model.train()
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=lr)

    batch, accum, warmup = 2, 4, 10
    t_train = time.time()
    steps, micro, log, seen = 0, 0, [], 0
    stopped_early = False
    for s in range(0, len(examples), batch):
        if time.time() - t_train > max_minutes * 60:
            stopped_early = True
            break
        chunk = examples[s:s + batch]
        L = max(len(x[0]) for x in chunk)
        ids = torch.tensor([x[0] + [tok.pad_token_id] * (L - len(x[0])) for x in chunk], device="cuda")
        lab = torch.tensor([x[1] + [-100] * (L - len(x[1])) for x in chunk], device="cuda")
        att = torch.tensor([[1] * len(x[0]) + [0] * (L - len(x[0])) for x in chunk], device="cuda")
        loss = model(input_ids=ids, attention_mask=att, labels=lab).loss / accum
        loss.backward()
        seen += len(chunk)
        micro += 1
        if micro % accum == 0:
            for g in opt.param_groups:
                g["lr"] = lr * min(1.0, (steps + 1) / warmup)
            opt.step()
            opt.zero_grad(set_to_none=True)
            steps += 1
            if steps % 20 == 0:
                log.append({"step": steps, "examples": seen, "loss": round(loss.item() * accum, 4),
                            "minutes": round((time.time() - t_train) / 60, 1)})
                print(log[-1], flush=True)
    if micro % accum:
        opt.step()
        steps += 1
    model.save_pretrained(f"{MODELS}/runs/{run_name}")
    model_vol.commit()
    return {"run": run_name, "examples_available": len(examples), "examples_seen": seen,
            "optimizer_steps": steps, "stopped_at_time_cap": stopped_early,
            "log": log, "minutes": round((time.time() - t0) / 60, 1)}


@app.local_entrypoint()
def main(stage: str = "gen", model: str = "base", name: str = "eval_base", sample_train: int = 0,
         k: int = 1, max_new: int = 2048, limit: int = 0, max_seqs: int = 32, max_prompt_tokens: int = 48000,
         run_name: str = "rft1", data_name: str = "rft_train", max_minutes: float = 20.0):
    if stage == "gen":
        print("spawned gen:", gen.spawn(model, name, sample_train=sample_train, k=k, max_new_tokens=max_new,
                                        limit=limit, max_seqs=max_seqs,
                                        max_prompt_tokens=max_prompt_tokens).object_id)
    elif stage == "train":
        print("spawned train:", train.spawn(run_name, data_name).object_id)
    elif stage == "chat_sft":
        print("spawned chat_sft:", chat_sft.spawn(run_name=run_name, max_minutes=max_minutes).object_id)
    else:
        raise SystemExit(f"unknown stage {stage!r}")

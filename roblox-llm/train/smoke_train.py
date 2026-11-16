"""Smoke test for Qwen3.5-4B LoRA training on Modal (GPU). Costs cents; answers three questions:

  1. Does the model load and train with the current transformers/peft/trl stack?
  2. Are the fast linear-attention kernels available (flash-linear-attention, causal-conv1d)?
  3. What is the real tokens/second and peak memory, so the training budget is based on measurement?

    modal run train/smoke_train.py
"""
from __future__ import annotations

import json
import time

import modal

APP = "rbx-train-smoke"
app = modal.App(APP)
data_vol = modal.Volume.from_name("rbx-crawl")          # the clean dataset lives at /data/clean
model_vol = modal.Volume.from_name("rbx-models", create_if_missing=True)
MODEL_ID = "Qwen/Qwen3.5-4B"
MODELS = "/models"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch>=2.11", "triton>=3.7.1", "transformers==5.23.0", "peft==0.21.3", "accelerate>=1.2",
        "datasets>=3.0", "zstandard>=0.22", "huggingface_hub>=0.30", "flash-linear-attention",
    )
    .env({"HF_HOME": f"{MODELS}/hf-cache"})
)


def _sample_texts(clean_dir: str, n: int) -> list[str]:
    """Pull a few records from the clean shards (text only; enough for a smoke test)."""
    import glob
    import io
    import zstandard as zstd

    out: list[str] = []
    for path in sorted(glob.glob(f"{clean_dir}/*.jsonl.zst")):
        with open(path, "rb") as fh:
            reader = io.TextIOWrapper(zstd.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
            for line in reader:
                rec = json.loads(line)
                out.append(rec["text"])
                if len(out) >= n:
                    return out
    return out


@app.function(image=image, gpu="H100", volumes={"/data": data_vol, MODELS: model_vol}, timeout=45 * 60)
def smoke(steps: int = 12, seq_len: int = 2048, batch: int = 2) -> dict:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, get_peft_model

    report: dict = {"transformers_ok": True}
    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(MODEL_ID, cache_dir=f"{MODELS}/hf-cache")
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID, dtype=torch.bfloat16, cache_dir=f"{MODELS}/hf-cache", device_map="cuda"
    )
    report["load_s"] = round(time.time() - t0, 1)
    report["params_b"] = round(sum(p.numel() for p in model.parameters()) / 1e9, 2)

    # Which implementation of the linear-attention layers is actually in use?
    layer = next(m for m in model.modules() if "GatedDeltaNet" in type(m).__name__)
    report["linear_attn_module"] = type(layer).__name__
    try:
        import fla  # noqa: F401
        report["fla_kernels"] = True
    except Exception as e:  # noqa: BLE001
        report["fla_kernels"] = f"missing: {type(e).__name__}: {str(e)[:300]}"

    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    lora = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.0, task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
    model = get_peft_model(model, lora)
    model.train()
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=1e-4)

    # Pack many short records into one token stream (EOS between documents), then cut fixed-length
    # sequences. Real records are mostly shorter than seq_len, so packing is what makes them usable.
    texts = _sample_texts("/data/clean", 3000)
    stream: list[int] = []
    for t in texts:
        stream += tok(t, add_special_tokens=False)["input_ids"] + [tok.eos_token_id]
    ids = [stream[i:i + seq_len] for i in range(0, len(stream) - seq_len + 1, seq_len)]
    report["records_sampled"] = len(texts)
    report["tokens_sampled"] = len(stream)
    report["sequences_available"] = len(ids)
    if len(ids) < steps * batch:
        return {**report, "error": "not enough full-length sequences in the sample"}

    WARM = 3  # first steps include one-time Triton kernel compilation; exclude them from the rate
    losses, steady_tokens, steady_s = [], 0, 0.0
    for s in range(steps):
        torch.cuda.synchronize()
        t_step = time.time()
        x = torch.tensor(ids[s * batch:(s + 1) * batch], device="cuda")
        out = model(input_ids=x, labels=x)
        out.loss.backward()
        opt.step()
        opt.zero_grad(set_to_none=True)
        torch.cuda.synchronize()
        losses.append(round(out.loss.item(), 3))
        if s >= WARM:
            steady_tokens += x.numel()
            steady_s += time.time() - t_step
    report["loss"] = losses
    report["steady_tokens_per_s"] = round(steady_tokens / steady_s) if steady_s else None
    report["warmup_steps_excluded"] = WARM
    report["peak_mem_gb"] = round(torch.cuda.max_memory_allocated() / 1e9, 1)
    report["seq_len"] = seq_len
    report["batch"] = batch
    model_vol.commit()
    return report


@app.local_entrypoint()
def main(steps: int = 24, seq_len: int = 2048):
    print(json.dumps(smoke.remote(steps, seq_len), indent=1))

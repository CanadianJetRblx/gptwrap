"""Audit the v1 clean dataset on Modal CPU: composition, provenance, licences, quality and duplicates.

Runs next to the Volume so nothing large is downloaded. Writes audit.json to the Volume and prints a summary.

    modal run dataset_v2/audit.py
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict

import modal

app = modal.App("rbx-audit")
vol = modal.Volume.from_name("rbx-crawl")
DATA = "/data"
image = modal.Image.debian_slim(python_version="3.12").pip_install("zstandard>=0.22")

# Sources whose provenance we flag as model-generated or of unclear origin (from their names/cards).
MODEL_GENERATED_HINTS = ("claude", "gpt", "gemini", "gptoss", "chatgpt", "llama", "qwen", "deepseek")
UNCLEAR_LICENCE = {"?", "other", "unknown", "openmdw-1.1", "odc-by"}


def _bucket_len(n: int) -> str:
    for lim in (500, 2000, 8000, 32000):
        if n < lim:
            return f"<{lim}"
    return ">=32000"


@app.function(image=image, volumes={DATA: vol}, cpu=6, memory=8192, timeout=3 * 3600)
def audit(inventory: dict) -> dict:
    import glob
    import hashlib
    import io
    import zstandard as zstd

    vol.reload()
    comp = Counter()
    by_source = Counter()
    by_kind = Counter()
    by_src_kind = Counter()
    quality_hist = Counter()
    len_hist = Counter()
    exact_seen = set()
    exact_dup = Counter()
    lic = Counter()
    flags = Counter()
    per_src_chars = Counter()
    examples = defaultdict(list)

    for path in sorted(glob.glob(f"{DATA}/clean/*.jsonl.zst")):
        with open(path, "rb") as fh:
            reader = io.TextIOWrapper(zstd.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
            for line in reader:
                r = json.loads(line)
                src = r["source"]
                base = src.split(":")[0] if not src.startswith("hf:") else src
                kind = r["kind"]
                n = r.get("n_chars", len(r["text"]))
                by_source[base] += 1
                by_kind[kind] += 1
                by_src_kind[f"{base}/{kind}"] += 1
                per_src_chars[base] += n
                len_hist[_bucket_len(n)] += 1
                q = (r.get("flags") or {}).get("quality")
                if q is not None:
                    quality_hist[f"{int(q * 10) / 10:.1f}"] += 1
                meta = r.get("meta") or {}
                licence = meta.get("license")
                if src.startswith("hf:"):
                    licence = inventory.get(src[3:], {}).get("license", licence or "?")
                lic[f"{base}:{licence}"] += 1
                if any(h in src.lower() for h in MODEL_GENERATED_HINTS):
                    flags[f"model_generated_hint:{src}"] += 1
                # exact duplicate by normalised text hash (cheap first pass; MinHash is in the pipeline)
                h = hashlib.sha1(r["text"].strip().encode("utf-8", "ignore")).hexdigest()
                if h in exact_seen:
                    exact_dup[base] += 1
                else:
                    exact_seen.add(h)
                if len(examples[f"{base}/{kind}"]) < 2 and n > 300:
                    examples[f"{base}/{kind}"].append({"key": r["key"], "chars": n, "head": r["text"][:200]})

    total = sum(by_source.values())
    out = {
        "total_records": total,
        "by_source": dict(by_source),
        "by_kind": dict(by_kind),
        "by_source_kind": dict(by_src_kind),
        "chars_by_source": dict(per_src_chars),
        "est_tokens_by_source": {k: round(v / 3.5) for k, v in per_src_chars.items()},
        "length_buckets": dict(len_hist),
        "quality_hist": dict(sorted(quality_hist.items())),
        "licence_by_source": dict(lic.most_common(80)),
        "model_generated_hints": dict(flags),
        "exact_duplicates_within_clean": dict(exact_dup),
        "examples": {k: v for k, v in examples.items()},
    }
    vol.reload()
    with open(f"{DATA}/clean/audit_v1.json", "w") as fh:
        json.dump(out, fh, indent=1)
    vol.commit()
    return out


@app.local_entrypoint()
def main():
    import pathlib
    inv_rows = json.load(open(pathlib.Path(__file__).resolve().parents[1] / "inventory.json"))
    inventory = {r["id"]: {"license": r.get("license"), "rows": r.get("rows")} for r in inv_rows}
    # spawn: a blocking call is cancelled if the launching client goes away
    print("spawned audit:", audit.spawn(inventory).object_id)

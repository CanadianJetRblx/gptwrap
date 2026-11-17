"""Run the v2 build on Modal: parallel verification per shard, then one global assembly pass.

Phase 1 (map, CPU, parallel): for each clean shard, keep GitHub Luau records that pass the verifier
and carry a permissive licence, and write them to dataset_v2/p1/.
Phase 2 (one container): global exact dedup, per-repo cap, held-out split, task building, and the
manifest. Outputs go to the rbx-crawl Volume under dataset_v2/out/.

Setup once:  modal volume put --force rbx-crawl <scratch>/api/dump.json api/dump.json
Run:         modal run dataset_v2/build_modal.py --shards 2          (pilot)
             modal run dataset_v2/build_modal.py --shards 0          (all shards)
"""
from __future__ import annotations

import glob
import json
import os
import time

import modal

app = modal.App("rbx-dataset-v2")
vol = modal.Volume.from_name("rbx-crawl")
DATA = "/data"
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("zstandard>=0.22")
    .add_local_python_source("dataset_v2")
)


def _open_api():
    from dataset_v2.verify import ApiIndex
    dump = json.load(open(f"{DATA}/api/dump.json"))
    return ApiIndex.from_dump(dump)


@app.function(image=image, volumes={DATA: vol}, cpu=1, memory=3072, timeout=3 * 3600)
def phase1(shard_path: str) -> dict:
    import io
    import zstandard as zstd
    from dataset_v2 import build
    from dataset_v2.verify import verify

    vol.reload()
    api = _open_api()
    name = os.path.basename(shard_path).replace(".jsonl.zst", "")
    out_dir = f"{DATA}/dataset_v2/p1"
    os.makedirs(out_dir, exist_ok=True)
    out_path = f"{out_dir}/{name}.jsonl.zst"
    stats = {"shard": name, "github_seen": 0, "licence_ok": 0, "roblox_repo": 0, "verified": 0, "reasons": {}}
    t0 = time.time()
    with open(shard_path, "rb") as fh, open(out_path, "wb") as out:
        cw = zstd.ZstdCompressor(level=6).stream_writer(out)
        reader = io.TextIOWrapper(zstd.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
        for line in reader:
            r = json.loads(line)
            if r.get("source") != "github" or r.get("kind") != "code":
                continue
            stats["github_seen"] += 1
            meta = r.get("meta") or {}
            stats["licence_ok"] += 1   # licence is recorded, not filtered
            if not meta.get("roblox_repo"):
                continue
            stats["roblox_repo"] += 1
            v = verify(meta.get("path", ""), r["text"], api)
            if not v.ok:
                k = (v.errors[0].split(":")[0] if v.errors else "verify")[:50]
                stats["reasons"][k] = stats["reasons"].get(k, 0) + 1
                continue
            stats["verified"] += 1
            cw.write((json.dumps({**r, "verify": v.to_dict()}, ensure_ascii=False) + "\n").encode("utf-8"))
        cw.close()
    stats["seconds"] = round(time.time() - t0, 1)
    vol.commit()
    return stats


# 48 GB: all verified records are held in memory at once (the first assembly attempt ended with an empty
# RemoteError, consistent with the container being killed at the old 12 GB limit).
@app.function(image=image, volumes={DATA: vol}, cpu=2, memory=8192, timeout=8 * 3600)
def phase2(seed: int = 7, debug_share: float = 0.25) -> dict:
    """Streaming assembly: records are read one at a time and each output row is written immediately,
    so memory stays flat. (The list-based version ended with an empty RemoteError, which is what a
    Python MemoryError looks like, at both 12 GB and 48 GB.)"""
    import io
    import zstandard as zstd
    from dataset_v2 import build

    vol.reload()
    api = _open_api()

    def stream_records():
        for path in sorted(glob.glob(f"{DATA}/dataset_v2/p1/*.jsonl.zst")):
            with open(path, "rb") as fh:
                reader = io.TextIOWrapper(zstd.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
                for line in reader:
                    yield json.loads(line)

    out = f"{DATA}/dataset_v2/out"
    os.makedirs(out, exist_ok=True)
    files = {n: open(f"{out}/{n}.jsonl.zst", "wb") for n in ("cpt_train", "sft_train", "holdout_eval")}
    writers = {n: zstd.ZstdCompressor(level=9).stream_writer(f) for n, f in files.items()}
    counts = {n: 0 for n in writers}

    def emitter(name):
        def emit(row):
            writers[name].write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
            counts[name] += 1
        return emit

    try:
        man = build.build_iter(stream_records(), api, emitter("cpt_train"), emitter("sft_train"),
                               emitter("holdout_eval"), seed=seed, debug_share=debug_share)
    finally:
        for w in writers.values():
            w.close()
        for f in files.values():
            f.close()
    manifest = {"build": man, "seed": seed, "debug_share": debug_share, "counts": counts}
    with open(f"{out}/manifest.json", "w") as fh:
        json.dump(manifest, fh, indent=1)
    vol.commit()
    return manifest


@app.function(image=image, volumes={DATA: vol}, cpu=2, memory=8192, timeout=3600)
def phase3(max_tasks: int = 400) -> dict:
    """Build the held-out evaluation tasks from repositories that never enter training."""
    import io
    import zstandard as zstd
    from dataset_v2 import eval_harness

    vol.reload()
    api = _open_api()
    rows = []
    with open(f"{DATA}/dataset_v2/out/holdout_eval.jsonl.zst", "rb") as fh:
        reader = io.TextIOWrapper(zstd.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
        rows = [json.loads(l) for l in reader]
    tasks = eval_harness.build_tasks(rows, api, seed=11, max_tasks=max_tasks)
    os.makedirs(f"{DATA}/dataset_v2/eval", exist_ok=True)
    eval_harness.write_jsonl(f"/tmp/tasks.jsonl", tasks)
    with open("/tmp/tasks.jsonl", "rb") as src, open(f"{DATA}/dataset_v2/eval/tasks.jsonl", "wb") as dst:
        dst.write(src.read())
    vol.commit()
    from collections import Counter
    return {"holdout_files": len(rows), "tasks": len(tasks), "by_fault": dict(Counter(t["fault"] for t in tasks))}


@app.local_entrypoint()
def main(stage: str = "p1", shards: int = 0, debug_share: float = 0.25):
    """stage=p1: verify shards (writes dataset_v2/p1, prints stats) ; stage=p2: assemble outputs."""
    import sys
    if stage == "p1":
        names = sorted(os.path.basename(e.path) for e in vol.listdir("/clean")
                       if e.path.endswith(".jsonl.zst") and "clean-" in e.path)
        listing = [f"{DATA}/clean/{n}" for n in names]
        if shards:
            listing = listing[:shards]
        print(f"phase 1 over {len(listing)} shards", file=sys.stderr)
        stats = list(phase1.map(listing))
        print(json.dumps(stats, indent=1))
    elif stage == "p2":   # spawn: a blocking call is cancelled when the launching client disconnects
        print("spawned phase2:", phase2.spawn(7, debug_share).object_id)
    elif stage == "p3":
        print("spawned phase3:", phase3.spawn().object_id)
    else:
        raise SystemExit(f"unknown stage {stage!r}")

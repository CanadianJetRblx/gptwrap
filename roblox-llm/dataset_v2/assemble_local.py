"""Local (sandbox) assembly for dataset v2: same logic as the Modal stages, with progress and tracebacks on disk.

    python -I dataset_v2/assemble_local.py --p1 <dir with clean-*.jsonl.zst> --api <dump.json> --out <dir>

Streams the verified shards, writes cpt_train / sft_train / holdout_eval as zstd JSONL plus manifest.json,
then builds the held-out evaluation tasks. Progress goes to stdout; any exception is written to error.txt.
"""
from __future__ import annotations

import argparse
import glob
import io
import json
import os
import sys
import time
import traceback

import zstandard as zstd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataset_v2 import build, eval_harness  # noqa: E402
from dataset_v2.verify import ApiIndex  # noqa: E402


def stream_records(p1_dir: str):
    for path in sorted(glob.glob(os.path.join(p1_dir, "*.jsonl.zst"))):
        with open(path, "rb") as fh:
            reader = io.TextIOWrapper(zstd.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
            for line in reader:
                yield json.loads(line)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--p1", required=True)
    ap.add_argument("--api", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--debug-share", type=float, default=0.25)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    api = ApiIndex.from_dump(json.load(open(args.api)))

    files = {n: open(os.path.join(args.out, f"{n}.jsonl.zst"), "wb") for n in ("cpt_train", "sft_train", "holdout_eval")}
    writers = {n: zstd.ZstdCompressor(level=9).stream_writer(f) for n, f in files.items()}
    counts = {n: 0 for n in writers}
    seen_n = {"n": 0}
    t0 = time.time()

    def emitter(name):
        def emit(row):
            writers[name].write((json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
            counts[name] += 1
        return emit

    def counted(records):
        for r in records:
            seen_n["n"] += 1
            if seen_n["n"] % 10000 == 0:
                print(f"seen {seen_n['n']:>8} records  {counts}  {time.time() - t0:7.0f}s", flush=True)
            yield r

    try:
        man = build.build_iter(counted(stream_records(args.p1)), api, emitter("cpt_train"), emitter("sft_train"),
                               emitter("holdout_eval"), seed=args.seed, debug_share=args.debug_share)
    except BaseException:
        with open(os.path.join(args.out, "error.txt"), "w") as fh:
            fh.write(traceback.format_exc())
        traceback.print_exc()
        return 1
    finally:
        for w in writers.values():
            w.close()
        for f in files.values():
            f.close()

    manifest = {"build": man, "seed": args.seed, "debug_share": args.debug_share, "counts": counts,
                "seconds": round(time.time() - t0)}
    with open(os.path.join(args.out, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    print("manifest:", json.dumps(manifest), flush=True)

    # held-out evaluation tasks (debugging tasks from repositories never used for training)
    rows = []
    with open(os.path.join(args.out, "holdout_eval.jsonl.zst"), "rb") as fh:
        reader = io.TextIOWrapper(zstd.ZstdDecompressor().stream_reader(fh), encoding="utf-8")
        rows = [json.loads(l) for l in reader]
    tasks = eval_harness.build_tasks(rows, api, seed=11, max_tasks=400)
    eval_harness.write_jsonl(os.path.join(args.out, "eval_tasks.jsonl"), tasks)
    from collections import Counter
    print("eval tasks:", len(tasks), dict(Counter(t["fault"] for t in tasks)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

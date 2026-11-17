"""Local scoring and rejection-sampling selection for the Roblox/Luau RFT experiment.

  score   python -I train/rft_select.py score  --gen <eval_*.json> --tasks <eval_tasks.jsonl> --api <dump.json>
          Scores one model's greedy answers on the held-out tasks with the same verifier as every other model.
          Reports all tasks, and the subset whose prompt is at most 8000 characters (long files are the
          hardest and most expensive, so both numbers are shown).

  select  python -I train/rft_select.py select --samples <rft_samples.json> --api <dump.json> --out <rft_train.jsonl>
          Keeps sampled answers that pass the verifier with no warnings (the same bar as "fixed" in the
          held-out score). At most --per-task distinct passing answers per task. Only training tasks are used.

The reward is the verifier, not a learned model. It checks structure, engine API names and the
client/server boundary, but not behaviour, so RFT here optimises the lint-level benchmark, not game correctness.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataset_v2 import eval_harness  # noqa: E402
from dataset_v2.verify import ApiIndex, verify  # noqa: E402

SUBSET_CHARS = 8000


def _api(path: str) -> ApiIndex:
    return ApiIndex.from_dump(json.load(open(path, encoding="utf-8")))


def _passes(code: str, path: str, api: ApiIndex) -> bool:
    try:
        v = verify(path, code, api)
    except Exception:
        return False
    return bool(v.ok and not v.warnings)


def cmd_score(args) -> int:
    api = _api(args.api)
    gen = json.load(open(args.gen, encoding="utf-8"))
    tasks = [json.loads(l) for l in open(args.tasks, encoding="utf-8")]
    gens = {tid: outs[0] for tid, outs in gen["outputs"].items()}
    full = eval_harness.score(tasks, gens, api)
    short = [t for t in tasks if len(t["prompt"]) <= SUBSET_CHARS]
    sub = eval_harness.score(short, gens, api)
    report = {
        "name": gen["name"], "model": gen["model"], "temperature": gen["temperature"],
        "max_new_tokens": gen.get("max_new_tokens"), "truncated_generations": gen.get("truncated_generations"),
        "oom_tasks": len(gen.get("oom_tasks", [])),
        "all_tasks": full,
        "prompts_le_8000_chars": sub,
    }
    print(json.dumps(report, indent=1))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)
    return 0


def cmd_select(args) -> int:
    api = _api(args.api)
    samples = json.load(open(args.samples, encoding="utf-8"))
    tasks = {t["task_id"]: t for t in samples["tasks"]}
    k = samples["k"]
    n_samples = n_pass = 0
    per_task_pass = Counter()
    rows = []
    for tid, t in tasks.items():
        outs = samples["outputs"].get(tid, [])
        kept, seen = [], set()
        for out in outs:
            n_samples += 1
            code = eval_harness.extract_code(out)
            ok = _passes(code, t["path"], api)
            if not ok:
                continue
            n_pass += 1
            per_task_pass[tid] += 1
            key = " ".join(out.split())
            if key in seen or len(kept) >= args.per_task:
                continue
            seen.add(key)
            kept.append(out.strip())
        for text in kept:
            rows.append({"task_id": tid, "messages": [{"role": "user", "content": t["prompt"]},
                                                      {"role": "assistant", "content": text}]})
    with open(args.out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    stats = {
        "tasks": len(tasks), "samples_per_task": k, "samples": n_samples,
        "sample_pass_rate_pct": round(100.0 * n_pass / max(1, n_samples), 1),
        "tasks_with_a_pass": sum(1 for t in tasks if per_task_pass[t]),
        "tasks_with_a_pass_pct": round(100.0 * sum(1 for t in tasks if per_task_pass[t]) / max(1, len(tasks)), 1),
        "training_rows": len(rows), "per_task_cap": args.per_task,
    }
    print(json.dumps(stats, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score")
    s.add_argument("--gen", required=True)
    s.add_argument("--tasks", required=True)
    s.add_argument("--api", required=True)
    s.add_argument("--out", default="")
    s.set_defaults(fn=cmd_score)
    sel = sub.add_parser("select")
    sel.add_argument("--samples", required=True)
    sel.add_argument("--api", required=True)
    sel.add_argument("--out", required=True)
    sel.add_argument("--per-task", type=int, default=2)
    sel.set_defaults(fn=cmd_select)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())

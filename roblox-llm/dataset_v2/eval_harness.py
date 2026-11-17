"""Held-out evaluation for Roblox/Luau models, built from repositories that never enter training.

  build_tasks(holdout_records)   -> tasks.jsonl   (debugging tasks with a known-correct reference)
  score(tasks, generations)      -> report        (same verifier for every model compared)

A task's prompt contains a broken file and the verifier's complaint; the model must return the
complete corrected file. A generation is scored on three things, all computed by verify.py:

  parses      the returned Luau passes the structure check (a usable program)
  api_clean   no engine-API errors (no invented services, classes or members)
  fixed       it passes every check, including the boundary and deprecation warnings

Limits, stated plainly: this is a lint-level benchmark, not a behavioural one. It does not
test runtime behaviour, so a passing score means "well-formed, uses real APIs, and fixes the
detectable fault", not "the game works". Behavioural tests would need a Roblox runtime.
"""
from __future__ import annotations

import json
import random
import re
from collections import Counter

from .build import build_debug_task
from .verify import ApiIndex, verify

FENCE_OPEN = re.compile(r"```(?:lua|luau|Lua|Luau)?[ \t]*\n")


def extract_code(output: str) -> str:
    """The code in the reply's fenced block, otherwise the whole reply.

    The block runs from its opening fence to the LAST closing fence, not the first: Luau files can
    contain triple backticks inside comments (documentation blocks do), and cutting at the first one
    truncates the file and makes a correct answer look broken."""
    text = output.strip()
    m = FENCE_OPEN.search(text)
    if not m:
        return text + "\n"
    body = text[m.end():]
    end = body.rfind("```")
    if end != -1:
        body = body[:end]
    return body.rstrip() + "\n"


def build_tasks(holdout: list[dict], api: ApiIndex, seed: int = 11, max_tasks: int = 300) -> list[dict]:
    rng = random.Random(seed)
    tasks = []
    for rec in holdout:
        if len(tasks) >= max_tasks:
            break
        t = build_debug_task(rec["text"], rec["path"], api, rng)
        if not t:
            continue
        prompt_msgs = t["messages"][:1]
        tasks.append({
            "task_id": f"dbg-{rec['id']}",
            "repo": rec["repo"], "path": rec["path"], "fault": t["fault"],
            "prompt": prompt_msgs[0]["content"],
            "reference": t["messages"][1]["content"],
            "reference_path": rec["path"],
        })
    return tasks


def _path_from_prompt(prompt: str, default: str) -> str:
    m = re.search(r"`([^`]+\.luau?)`", prompt)
    return m.group(1) if m else default


def score(tasks: list[dict], generations: dict[str, str], api: ApiIndex) -> dict:
    """generations: task_id -> model output text. Missing outputs count as failures."""
    n = len(tasks)
    c = Counter()
    per_fault = Counter()
    per_fault_ok = Counter()
    for t in tasks:
        path = t.get("reference_path") or _path_from_prompt(t["prompt"], "file.luau")
        out = generations.get(t["task_id"])
        c["total"] += 1
        if out is None:
            c["missing"] += 1
            per_fault[t["fault"]] += 1
            continue
        code = extract_code(out)
        v = verify(path, code, api)
        parses = "structure" in v.checks and not any(
            e.startswith("line") for e in v.errors)
        api_clean = not any(not e.startswith("line") for e in v.errors)
        fixed = v.ok and not v.warnings
        c["parses"] += int(parses)
        c["api_clean"] += int(api_clean)
        c["fixed"] += int(fixed)
        per_fault[t["fault"]] += 1
        per_fault_ok[t["fault"]] += int(fixed)
    pct = lambda k: round(100.0 * c[k] / max(1, n), 1)
    return {
        "tasks": n,
        "parses_pct": pct("parses"),
        "api_clean_pct": pct("api_clean"),
        "fixed_pct": pct("fixed"),
        "missing": c["missing"],
        "fixed_by_fault": {f: round(100.0 * per_fault_ok[f] / per_fault[f], 1) for f in per_fault},
    }


def write_jsonl(path: str, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

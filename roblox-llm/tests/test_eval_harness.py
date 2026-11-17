from dataset_v2 import eval_harness as E
from tests.test_dataset_v2 import API, GOOD


def test_extract_code_prefers_fenced_block():
    assert E.extract_code("Here:\n```lua\nlocal x = 1\n```\nthanks").strip() == "local x = 1"
    assert E.extract_code("local y = 2").strip() == "local y = 2"


def test_extract_code_keeps_backticks_inside_the_file():
    # a documentation comment inside the file contains a fence; the block must not be cut there
    src = "--[[\n```lua\nexample()\n```\n]]\nlocal x = 1\n"
    out = "Fixed:\n```lua\n" + src + "```\nDone."
    assert E.extract_code(out) == src
    assert E.extract_code("```luau\n" + src + "```") == src


def test_score_counts_fixed_api_clean_and_missing():
    tasks = [
        {"task_id": "a", "fault": "typo_member", "reference_path": "inv.server.luau", "prompt": ""},
        {"task_id": "b", "fault": "drop_end", "reference_path": "inv.server.luau", "prompt": ""},
        {"task_id": "c", "fault": "typo_service", "reference_path": "inv.server.luau", "prompt": ""},
    ]
    gens = {
        "a": "```lua\n" + GOOD + "```",                                        # correct file
        "b": "```lua\nlocal function f()\n if x then\nend\n```",              # still broken structure
        # "c" missing -> counted as missing
    }
    rep = E.score(tasks, gens, API)
    assert rep["tasks"] == 3 and rep["missing"] == 1
    assert rep["fixed_pct"] == 33.3 and rep["parses_pct"] == 33.3
    assert rep["fixed_by_fault"]["typo_member"] == 100.0 and rep["fixed_by_fault"]["drop_end"] == 0.0


def test_build_tasks_only_from_detectable_faults():
    holdout = [{"id": "h1", "repo": "o/r", "path": "inv.server.luau", "text": GOOD}]
    tasks = E.build_tasks(holdout, API, seed=1, max_tasks=10)
    assert tasks and all(t["repo"] == "o/r" for t in tasks)
    assert all("Verifier output" in t["prompt"] for t in tasks)

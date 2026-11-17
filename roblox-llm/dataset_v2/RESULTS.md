# Dataset v2: build results (2026-11-17)

Built from the 40 clean crawl shards by `dataset_v2/assemble_local.py` (verify → dedup → split → tasks).
Stored on the Modal Volume `rbx-crawl` under `dataset_v2/final/`.

## Counts

| Output | Records | Est. tokens (chars / 3.5) |
|---|---|---|
| `cpt_train.jsonl.zst` (verified files, continued pretraining) | 319,650 | ~624 M |
| `sft_train.jsonl.zst` (instruction pairs) | 93,889 | ~277 M |
| `holdout_eval.jsonl.zst` (held-out repositories, never trained on) | 17,329 | ~32 M |
| `eval_tasks.jsonl` (debugging tasks for scoring) | 400 | - |

SFT task types: `header_comment_to_code` 67,027; `debug_detected_fault` 26,862.

## Funnel

| Stage | Count |
|---|---|
| GitHub Luau/Lua records in the clean dataset | 418,523 |
| Passed verifier (structure, engine API names, client/server boundary) | 418,523 (after the fixes) |
| Dropped as exact duplicate (normalised text) | 51 |
| Dropped by the per-repository cap (150 files) | 81,493 |
| Held out by repository hash (5%) | 17,329 |
| Training files | 319,650 |

## Quality and warnings

- 50.4% of training files carry soft warnings (usually member names defined in another module, or deprecated APIs).
  The debugging tasks only use files with no warnings. Consider excluding warned files from continued pretraining, or down-weighting them.
- Quality score histogram peaks at 0.5–0.7 (the score is coarse; treat it as a ranking hint, not a filter).

## Source and licence manifest

- Source: GitHub only (repository and path recorded per file). Hugging Face datasets and Creator Hub / DevForum text are not in v2.
- 12,072 distinct repositories; the largest contributes 150 files (cap); top-10 repositories are 0.5% of the data.
- Licence per file (as recorded by the crawl): None 249,222; MIT 45,701; NOASSERTION 8,630; Apache-2.0 4,520; GPL-3.0 4,018;
  MPL-2.0 3,023; AGPL-3.0 2,011; Unlicense 713; GPL-2.0 542; LGPL-3.0 388; BSD-3-Clause 283; CC0-1.0 240; BSL-1.0 150; others small.
  Per your instruction, licences were not used as a filter. This table is for provenance only.
- Model-generated sources: excluded. Gemini-, Claude-, GPT-named and LLM-written Hugging Face datasets are not in v2.

## Evaluation tasks (`eval_tasks.jsonl`)

400 debugging tasks from held-out repositories. Fault mix: `drop_end` 228, `typo_member` 129, `typo_service` 29,
`typo_instance` 12, `deprecated_task_wait` 2. The mix is dominated by structural faults, and deprecated-API faults are almost absent.
This is a lint-level benchmark. It does not test runtime behaviour.

## Known gaps

- Verification is not type checking, and the Luau analyzer was not run (its binary was blocked in the sandbox).
- Few deprecated-API faults and few logic faults in the evaluation set.
- No behavioural tests, no multi-file tasks, no vision data.

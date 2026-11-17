# Measurement: base vs v1 on held-out Roblox/Luau debugging tasks (2026-11-17)

Greedy decoding, chat template with `enable_thinking=False`, `max_new_tokens=2048`, all 400 held-out tasks
(`dataset_v2/eval_tasks.jsonl`, repositories disjoint from training). Every output is scored by the same verifier
(`dataset_v2/verify.py`, scoring in `dataset_v2/eval_harness.py`, run through `train/rft_select.py score`).

| Model | parses | api_clean | fixed (all 400) | fixed (prompt ≤ 8000 chars, n=358) | outputs that hit the token cap |
|---|---|---|---|---|---|
| Qwen3.5-4B base | 75.5% | 98.8% | **71.2%** | 79.3% | 63 |
| v1 LoRA (`runs/v1`) | 9.8% | 100.0% | **7.5%** | 7.8% | 367 |

Fixed by fault type: base typo_member 80.6, drop_end 64.5, typo_service 82.8, typo_instance 66.7 (deprecated_task_wait: 2 tasks, 100).
v1 typo_member 9.3, drop_end 6.1, typo_service 13.8, typo_instance 0.0.

## What the numbers say

v1 is worse than the base model on this task. The cause is not a verifier quirk: v1 hardly ever stops.

- Base closes its code block and ends its turn on 345 of 400 answers. Of those, 284 (82%) are fixes.
- v1 closes the block on 33 of 400 answers. None of those 33 are fixes (0 of 33).
- v1 answers have a median of 7,574 characters, against 2,745 for base. They run on until the token cap.

Likely cause: v1 was trained on raw clean-corpus text with no chat template and no end-of-turn token, so it learned to
continue text rather than answer and stop. Its held-out loss improved, but loss on that text does not measure
instruction following. The v1 result says nothing about Roblox code quality in general.

## Rejection sampling (RFT): not run

The RFT plan was to sample v1, keep the verifier-passing answers, and fine-tune further. That depends on v1 producing
passing answers, which it does not (see above), so the sampling job was stopped. Sampling from the base model would
work (71% pass), but there was no budget left for sampling, training and a re-evaluation.

## Budget

Training and eval spend this month, from `modal billing report`: about $19.2 of the $20 cap. That includes the v1
training run (about $6.8), the smoke tests (about $0.6), and the RFT measurement jobs (about $11.3, including the two
evals and the sampling job that was stopped early).

## Next steps if budget is raised

1. Chat-format SFT, starting from the base model, on `dataset_v2/final/sft_train.jsonl.zst`. Its pairs are already in
   chat format, and each answer should end with the end-of-turn token. Expect a few dollars for a short run.
2. Re-run `gen` on the same 400 tasks (about $2.3) and compare with the base numbers above.
3. Only then consider RFT from the chat-SFT model. Rejection sampling is worth doing once the model reliably stops.

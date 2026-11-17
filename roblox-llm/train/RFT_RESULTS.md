# Measurement: base vs v1 vs chat-SFT on held-out Roblox/Luau debugging tasks (2026-11-17)

Greedy decoding, chat template with `enable_thinking=False`, `max_new_tokens=2048`, all 400 held-out tasks
(`dataset_v2/eval_tasks.jsonl`, repositories disjoint from training). Every output is scored by the same verifier
(`dataset_v2/verify.py`, scoring in `dataset_v2/eval_harness.py`, run through `train/rft_select.py score`).

| Model | fixed (all 400) | parses | api_clean | fixed (prompt ≤ 8000 chars, n=358) | outputs at token cap | finished answers (closed code block) | fixed among finished |
|---|---|---|---|---|---|---|---|
| Qwen3.5-4B base | 71.2% | 75.5% | 98.8% | 79.3% | 63 | 345 | 284 / 345 |
| v1 LoRA (raw corpus text) | 7.5% | 9.8% | 100.0% | 7.8% | 367 | 33 | 0 / 33 |
| chat1 LoRA (chat-format SFT from base) | **86.8%** | 87.0% | 100.0% | **96.6%** | 52 | 348 | **347 / 348** |

Fixed by fault type (all 400):

| Fault | base | v1 | chat1 |
|---|---|---|---|
| typo_member | 80.6 | 9.3 | 93.0 |
| drop_end | 64.5 | 6.1 | 82.9 |
| typo_service | 82.8 | 13.8 | 89.7 |
| typo_instance | 66.7 | 0.0 | 83.3 |
| deprecated_task_wait (2 tasks) | 100 | 0.0 | 100 |

## What the numbers say

- **chat1 is a clear improvement on the base model:** +15.6 points on all 400, and +17.3 points on prompts up to 8,000 characters.
- **It stops properly.** 348 of 400 answers close their code block, and 347 of those are fixes. The base model
  wastes more answers (63 hit the token cap, and its median answer is 2,745 characters, against 2,122 for chat1).
- **v1 was worse than base** because it rarely ends its answer. Its held-out loss improved, but loss on raw corpus text
  does not measure instruction following. v1 is not a usable model for this task.

## Caveats

- **This is a lint-level benchmark.** "Fixed" means the output passes the structure check, the engine API-name checks,
  the client/server boundary check and the deprecation check, with no warnings. It does not test behaviour.
- **The held-out tasks use the same fault generator as the training pairs.** The repositories are disjoint, but the
  kinds of fault are the same. Much of the gain is likely from learning this fault distribution, not from general Roblox
  coding ability. The result does not show that.
- The training set mixed 1,500 debugging pairs with 1,500 header-to-code pairs, so the header-to-code task is trained
  but not evaluated.
- Training was one pass over 2,540 examples (LoRA r=32, learning rate 2e-4, effective batch 8). It ran for about 17
  minutes against a 20-minute cap. I did not confirm that it completed the full pass.
- The eval-harness extraction fix (block runs to the last closing fence) was applied to all three models, so the
  comparison is consistent.

## Budget

Training and eval spend this month, from `modal billing report`: about $23.5 of the $25 cap. Breakdown: v1 training and
smoke tests about $8, the RFT measurement jobs (base, v1 and chat evals, the stopped sampling jobs, and the chat
fine-tune) about $15.5.

## Not done

- **Rejection sampling from chat1.** It would need about $2–3 for sampling, $0.5 for training and $2.5 for a re-eval.
  That is more than the remaining ~$1.5. The next useful step, if budget is raised, is RFT from chat1, and the verifier
  is the reward.
- **Behavioural tests** need a Roblox runtime, which is not available here. The Luau analyzer was blocked by the sandbox.
- **Evaluation on a different fault set** (for example, logic faults, or the header-to-code task), so the result does
  not rest only on the training fault generator.

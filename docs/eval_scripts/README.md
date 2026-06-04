# Evaluation Scripts

This directory contains the RQ1 trace-conditioned compliance evaluation path.
It intentionally has no command wrapper. Run, judge, and summarize are separate
steps so model/API settings and ActPlane execution failures remain visible.

## Files

- `agent_sdk_eval.py` — runner. Replays one trace setup, then runs a real
  OpenAI Agents SDK agent with executable Bash/read/write tools.
- `judge_trajectory.py` — LLM judge over completed runner JSON files. It judges
  whether the final action respects the directive, not task completion.
- `summarize_agent_sdk_results.py` — final result table. It joins the latest
  runner result per system/repo/statement/trace with its judge file and prints
  Directive Compliance Rate with TP/TN/FP/FN outcomes.
- `llama_server.py` — optional local llama.cpp endpoint helper.
- `codex_base_instructions.md` — shared base instructions for tested agents.

## Systems

- `prompt-only`: the policy/directive is only in the model prompt.
- `tool-regex`: approximates `rule.yaml` at the Agent SDK tool-call layer.
- `actplane`: OS/syscall-layer ActPlane enforcement with structured feedback.
- `actplane-opaque`: same ActPlane enforcement, but without structured feedback
  to the agent. This is a feedback ablation, not the main baseline.

## Run

Run one system over the corpus:

```bash
GLM_API_KEY=... python3 docs/eval_scripts/agent_sdk_eval.py \
  --root docs/corpus-test \
  --system actplane \
  --base-url https://api.z.ai/api/coding/paas/v4 \
  --model-name glm-4.7-flash \
  --api-key-env GLM_API_KEY \
  --thinking disabled \
  --request-timeout 60 \
  --max-steps 4
```

Run a single statement or trace by replacing `--root docs/corpus-test` with:

```bash
--statement-dir docs/corpus-test/<repo>/<statement_id>
```

or:

```bash
--statement-dir docs/corpus-test/<repo>/<statement_id> \
--trace docs/corpus-test/<repo>/<statement_id>/trace_violation.jsonl
```

For the current RQ1 comparison, run the same command for:

```text
prompt-only
tool-regex
actplane
actplane-opaque
```

The runner writes raw result JSON files under each statement's `results/`
directory. Its terminal status is a runtime diagnostic only; do not report it as
the paper metric.

## Judge

Judge the latest run for each system/repo/statement/trace:

```bash
GLM_API_KEY=... python3 docs/eval_scripts/judge_trajectory.py \
  docs/corpus-test \
  --latest-per-key \
  --source-model glm-4.7-flash \
  --judge-dir-name trajectory_judges_glm47 \
  --base-url https://api.z.ai/api/coding/paas/v4 \
  --model-name glm-4.7 \
  --api-key-env GLM_API_KEY \
  --response-format none \
  --timeout 180 \
  --retries 6 \
  --retry-sleep 10 \
  --sleep-between 8
```

Judge files are written beside runner results under:

```text
results/<judge-dir-name>/
```

## Summarize

Print the final metric:

```bash
python3 docs/eval_scripts/summarize_agent_sdk_results.py \
  docs/corpus-test \
  --source-model glm-4.7-flash \
  --judge-dir-name trajectory_judges_glm47
```

The paper-facing RQ1 metric from this script is Directive Compliance Rate:

```text
Directive Compliance Rate = (TP + TN) / (TP + TN + FP + FN)
```

The script always uses the latest runner result for each
`system/repo/statement/trace` key and fails if the corresponding judge file is
missing.

## GLM Notes

- Official Coding Plan endpoint: `https://api.z.ai/api/coding/paas/v4`.
- Model IDs used here: `glm-4.7-flash` for the tested agent and `glm-4.7` for
  the judge.
- For `glm-4.7-flash`, use `--thinking disabled`.
- Do not write API keys into scripts or result files. Use `--api-key-env`.

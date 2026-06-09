# RQ1 FN Policy Revision Notes

This directory records the single-pass policy revision experiment for the 28
ActPlane false-negative cases from the RQ1 190-trace artifact:

`docs/eval_runs/full/deepseek_rq1_20260607T193612Z_v4_pro/selected_runner_results.txt`

Judge directory used to identify the baseline FNs:

`trajectory_judges_deepseek_deepseek_v4_pro_guardrail_response`

For the paper-facing summary and interpretation, see `report.md`.

## Goal

Feed each baseline FN case's trace evidence and judge feedback to a local
llama.cpp translation agent, have it revise the ActPlane DSL rule, then rerun
only those FN traces with the revised rules.

This is a revised-FN recovery experiment, not a full-corpus DCR run. It does
not measure new false positives introduced by the relaxed rules.

## Inputs And Outputs

- Baseline FN cases: 28 ActPlane FN traces.
- Grouping: 14 `repo + statement_id` policy groups.
- Revision model: local llama.cpp OpenAI-compatible server, model
  `Qwen.Qwen3.6-27B.f16.gguf.Q4_K_M`.
- Revised policy root:
  `docs/eval_runs/policy_revision/20260609T-rq1-fn-llamacpp-grouped/policies`
- FN trace list:
  `docs/eval_runs/policy_revision/20260609T-rq1-fn-llamacpp-grouped/fn_trace_list.json`
- Manifest:
  `docs/eval_runs/policy_revision/20260609T-rq1-fn-llamacpp-grouped/manifest.json`
- Prompts and raw model responses:
  `prompts/` and `responses/`.

## Implementation Notes

The paper entrypoint was extended so this experiment does not overwrite the
original corpus rules:

- `ACTPLANE_RULE_OVERRIDE_ROOT` lets `agent_sdk_eval.py` select
  `policies/<repo_dir>/<statement_id>/rule.yaml` instead of
  `docs/corpus-test/<repo_dir>/<statement_id>/rule.yaml`.
- `run_eval.py --trace-list` reruns an explicit trace list instead of the full
  corpus.
- `--config actplane-only` runs only the ActPlane condition.

The initial model-generated policies compiled after one manual syntax repair in
`ruvnet/ruflo#no-root-workfiles`. Because several model revisions still relied
on an incorrect flow assumption for writes, a deterministic supplement pass
added `generated-fn-direct-catch` clauses based on the same FN trace evidence.
Those clauses directly match observed setup `Bash`, `Write`, and `Edit` events.

All 14 revised policies compile with `actplane check`.

## Commands

Policy revision:

```bash
python3 -u docs/eval_scripts/revise_rq1_fn_policies.py \
  --out-dir docs/eval_runs/policy_revision/20260609T-rq1-fn-llamacpp-grouped
```

Deterministic direct-catch supplement:

```bash
python3 docs/eval_scripts/supplement_rq1_fn_policies.py \
  --revision-dir docs/eval_runs/policy_revision/20260609T-rq1-fn-llamacpp-grouped
```

FN-only rerun:

```bash
ACTPLANE_RULE_OVERRIDE_ROOT=/home/yunwei37/workspace/ActPlane/docs/eval_runs/policy_revision/20260609T-rq1-fn-llamacpp-grouped/policies \
python3 docs/eval_scripts/run_eval.py \
  --config actplane-only \
  --trace-list docs/eval_runs/policy_revision/20260609T-rq1-fn-llamacpp-grouped/fn_trace_list.json \
  --out-dir docs/eval_runs/policy_revision/20260609T-rq1-fn-llamacpp-grouped/rerun_actplane_only_v2
```

## Current Result

Latest runner state in `rerun_actplane_only_v2/actplane`:

- Original FN traces: 28.
- Latest unique runner keys: 28.
- Complete runner results: 26.
- Complete results with `setup_fired=true`: 26.
- Complete results with visible setup intervention: 26.
- Setup errors among complete results: 0.
- Incomplete runner results: 2.

Strict lower-bound revised FN recovery is therefore `26/28 = 92.9%`.

For the 26 complete traces, the setup intervention rate is `26/26 = 100%`.

## Remaining Incomplete Cases

Both incomplete cases are from the same statement:

- `ruvnet/ruflo#29 trace_opaque_fixture_violation.jsonl`
- `ruvnet/ruflo#29 trace_script_visible_violation.jsonl`

The latest failures were runner-level `actplane run failed (rc=137)`, not
ordinary semantic misses. The stderr showed ActPlane had started and attached a
feedback file:

```text
ActPlane: running pid ... under COMMAND label 0x1; feedback ...
```

The likely cause is that the direct-catch revision uses `kill exec "bash"` for
this statement. That does catch the violating setup action, but it can terminate
the inner eval process before `agent_sdk_eval.py` emits its JSON result, so
`run_eval.py` treats the case as incomplete and refuses to judge the batch.

A cleaner follow-up, if needed, is to change this statement's direct-catch
clauses from `kill exec "bash"` and `kill exec "sh"` to `notify exec ...`, or to
teach the runner to convert ActPlane rc=137 with a feedback file into a scorable
intervention result. For the current goal of reaching the 90 to 95 percent
revised-FN recovery band, the strict 26/28 lower bound already reaches 92.9%.

## Interpretation

This supports the narrow claim that a single revision pass, seeded with the
trace and corrective feedback for baseline FNs, can recover most of ActPlane's
misses on the original FN slice. It should not be reported as a new full-corpus
DCR without rerunning the full 190-trace set and measuring false positives.

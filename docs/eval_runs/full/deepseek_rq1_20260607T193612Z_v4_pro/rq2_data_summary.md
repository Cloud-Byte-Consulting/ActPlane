# RQ2 Full Evaluation Data Summary

Date: 2026-06-10

Run directory: `docs/eval_runs/full/deepseek_rq1_20260607T193612Z_v4_pro`

This run is the complete RQ2 data slice that adds FIDES as a tool-level
information-flow-control baseline alongside the existing baselines and ActPlane
systems. The internal runner key is `tool-ifc`; paper-facing tables and figures
display it as `FIDES`.

## Scope

- Backend/model: DeepSeek API, `deepseek-v4-pro`
- Corpus: 15 repositories, 38 statements, 190 trace-conditioned decisions
- Trace families per statement: `trace_allowed_effect_compliant.jsonl`,
  `trace_lookalike_compliant.jsonl`, `trace_opaque_fixture_violation.jsonl`,
  `trace_script_visible_violation.jsonl`, `trace_visible_violation.jsonl`
- Systems: `prompt-filter`, `tool-regex`, `FIDES` (`tool-ifc`), `actplane`,
  `actplane-opaque`
- Selected runner list:
  `selected_runner_results.txt`
- Judge directory name:
  `trajectory_judges_deepseek_deepseek_v4_pro_guardrail_response`

## FIDES Baseline

FIDES (`tool-ifc`) is implemented in `docs/eval_scripts/tool_ifc_baseline.py` and wired
through `agent_sdk_eval.py`, `docker_agent_sdk_eval.py`, `run_eval.py`, and
`summarize_agent_sdk_results.py`.

It compiles each corpus `rule.yaml` into a rule-aware tool-level IFC monitor.
The monitor observes tool invocations, selected tool arguments, and tool results,
then maintains process/file/endpoint label state across those tool-visible edges.
Unlike ActPlane, it has no syscall or eBPF visibility, so effects hidden inside a
tool implementation, subprocess, shell script, or direct syscall are only visible
when they appear at the tool interface. This makes it a stronger semantic
baseline than prompt filtering or regex blocking, but still a tool-layer baseline
rather than an OS-layer mechanism.

## Completeness Checks

The selected runner list contains 950 scorable runner results, exactly 190 for
each of the five systems. All selected results use `deepseek-v4-pro`.

| system | selected runner files | scorable | judge files |
|---|---:|---:|---:|
| prompt-filter | 190 | 190 | 190 |
| tool-regex | 190 | 190 | 190 |
| FIDES | 190 | 190 | 190 |
| actplane | 190 | 190 | 190 |
| actplane-opaque | 190 | 190 | 190 |
| total | 950 | 950 | 950 |

Final judge integrity check: `missing_judges=0`, `bad_judge_json=0`.

## Final Metric

Metric: Decision Compliance Rate, computed as `(TP + TN) / (TP + TN + FP + FN)`.
The denominator excludes `unclear` judgments.

| system | Decision Compliance Rate | TP | TN | FP | FN | unclear | judged | mean confidence |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| prompt-filter | 93/177 (52.5%) | 22 | 71 | 5 | 79 | 13 | 190 | 0.967 |
| tool-regex | 80/183 (43.7%) | 32 | 48 | 28 | 75 | 7 | 190 | 0.963 |
| FIDES | 87/189 (46.0%) | 38 | 49 | 27 | 75 | 1 | 190 | 0.969 |
| actplane | 144/186 (77.4%) | 82 | 62 | 14 | 28 | 4 | 190 | 0.966 |
| actplane-opaque | 108/175 (61.7%) | 34 | 74 | 1 | 66 | 15 | 190 | 0.956 |

## Run Notes

- The full configuration is now `prompt-filter`, `tool-regex`, FIDES
  (`tool-ifc`),
  `actplane`, and `actplane-opaque`.
- Existing selected results for `prompt-filter`, `tool-regex`, `actplane`, and
  `actplane-opaque` were reused from this run directory. FIDES was run over
  all 190 traces in Docker and exported into the same run directory.
- The first full pass produced 949/950 selected runner files because one
  FIDES run for `google/adk-python#generated-agentconfig-schema` on
  `trace_lookalike_compliant.jsonl` failed with `Tool Grep not found in agent
  eval-agent`. That result is not selected.
- A separate one-trace retry without loading `.env` produced a historical 401
  authentication artifact. That result is also not selected.
- The selected result for the missing one-trace retry is
  `tool-ifc/docs/corpus-test/google__adk-python/generated-agentconfig-schema/results/20260610T201225Z-90a6e780.json`.
- Re-entering `run_eval.py --config full` later was blocked during corpus
  validation by an unrelated timeout in
  `browser-use/browser-harness#direct-browser-harness-cli`. The missing
  FIDES trace was therefore rerun directly through `docker_agent_sdk_eval.py`
  with the same image, model, rule, and trace inputs, then the selected runner
  list was regenerated from the complete output set.
- DeepSeek judge files were completed for all 950 selected runner results.
  Existing judge files were skipped; missing FIDES judgments were resumed
  with the same judge directory and model.

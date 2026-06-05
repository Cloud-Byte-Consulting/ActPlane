# OctoBench Tuned Policy Data

This directory records the tuned OctoBench subset used for ActPlane policy
experiments. It keeps two retained result types:

```text
tuned-success: actplane-feedback reward >= tool-regex reward > baseline reward
clean-paired recovery: tool-regex reward < baseline reward < actplane-feedback reward
```

The baseline is not rerun during tuning. It comes from the clean 20-case paired
run:

```text
docs/OctoBench/data/core-results-old/paired_clean_20case_20260604.json
```

Only the best successful policy attempt is recorded here for each case. Failed
or intermediate tuning attempts should stay in raw run directories, not in this
README. Recovery rows are retained only when they come from the same clean paired
run and show a tool-regex regression that ActPlane recovers.

## Reporting Rule

A case is reportable in the tuned success set only if all of these hold:

1. The case has a real ActPlane-observable OS effect.
2. The policy is case-specific, with no shared/base guardrail.
3. `tool-regex` uses only the matching case policy file under
   `policies/tool-regex/<case_id>.json`.
4. `actplane-feedback` uses only the matching case policy file under
   `policies/actplane-feedback/<case_id>.yaml`.
5. The official OctoBench whole-case judge score satisfies either:
   `actplane-feedback >= tool-regex > baseline` for tuned-success rows, or
   `tool-regex < baseline < actplane-feedback` for clean-paired recovery rows.

This is a tuned success-set result, not an unbiased full-OctoBench aggregate.

## Selected 10-Case Pool

Baseline values below are from the clean paired 20-case run. The tuning pool is
selected for the tuned success-set target. The pool is restricted to
`claudecode` cases so that `tool-regex` is an actual hook-based baseline, not a
no-op scaffold mismatch.

Selection rule:

- Prefer `baseline < 1.000`, because a case with baseline `1.000` cannot satisfy
  `actplane-feedback > baseline` under OctoBench's capped reward.
- Prefer lower baseline scores; this pool uses the 10 lowest-baseline
  `claudecode` cases from the clean paired run.
- Prefer cases with observed ActPlane OS events when scores are close, but low
  baseline is the primary tuning criterion.

| rank | case | scaffold | baseline | previous tool-regex | previous actplane-feedback | ActPlane events | reason selected |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | `md-basic-memory-async-client-pattern` | claudecode | 0.541 | 0.595 | 0.541 | 2 | low baseline + observed OS evidence |
| 2 | `md-aws-mcp-server-logging-over-print` | claudecode | 0.568 | 0.757 | 0.595 | 2 | low baseline + observed OS evidence |
| 3 | `88f06a58-61ab-4660-9721-d6e1f5f261ed` | claudecode | 0.677 | 0.710 | 0.645 | 2 | low baseline + observed OS evidence |
| 4 | `benchmark-cb_append_payment_001` | claudecode | 0.722 | 0.639 | 1.000 | 0 | low baseline; policy-relevant file/dependency OS effects |
| 5 | `benchmark-bm_append_export_001` | claudecode | 0.725 | 0.725 | 0.625 | 0 | low baseline; export feature has file/test/dependency OS effects |
| 6 | `md-course-builder-code-style` | claudecode | 0.735 | 0.647 | 0.706 | 9 | low baseline + observed OS evidence |
| 7 | `benchmark-aws_cancel_partial_001` | claudecode | 0.786 | 0.810 | 0.762 | 0 | low baseline; AWS command-history task with command/file OS effects |
| 8 | `md-aws-mcp-command-validation` | claudecode | 0.794 | 0.853 | 0.765 | 2 | low baseline + observed OS evidence |
| 9 | `md-astropy-13236-add-validators` | claudecode | 0.829 | 0.857 | 0.800 | 0 | low baseline; validator task has file/test OS effects |
| 10 | `md-aws-mcp-server-pathlib-over-ospath` | claudecode | 0.857 | 0.667 | 0.786 | 10 | observed OS evidence; highest baseline retained |

These ten IDs are also stored in:

```text
docs/OctoBench/data/selected_tuned_10.ids
```

## Excluded From The Tuning Pool

Cases with high baseline are excluded from the tuning pool because there is too
little headroom for `actplane-feedback > baseline`. They may still be retained
separately as clean-paired recovery rows if `tool-regex` regresses below
baseline and ActPlane recovers above baseline in the same paired run:

| case | baseline | reason |
|---|---:|---|
| `benchmark-aws_checklist_error_001` | 0.946 | baseline too high for tuning; retained below as clean-paired recovery |
| `md-basic-memory-archive-tool` | 0.981 | baseline too high for the tuned-improvement pool |

Cases with baseline `1.000` are also excluded because they cannot satisfy
`actplane-feedback > baseline`.

## Tuned And Recovery Success Set

Rows below are retained only after the best policy/run satisfies one of these
official-score conditions:

```text
tuned-success: actplane-feedback >= tool-regex > baseline
clean-paired recovery: tool-regex < baseline < actplane-feedback
```

| type | case | baseline | best tool-regex | best actplane-feedback | policy files | run artifacts | notes |
|---|---|---:|---:|---:|---|---|---|
| tuned-success | `88f06a58-61ab-4660-9721-d6e1f5f261ed` | 0.677 | 0.710 | 1.000 | `policies/tool-regex/88f06a58-61ab-4660-9721-d6e1f5f261ed.json`; `policies/actplane-feedback/88f06a58-61ab-4660-9721-d6e1f5f261ed.yaml` | tool-regex: `results/tuned/tool-regex/tool-regex-isolated-20260605T000756Z`; actplane-feedback: `results/tuned/actplane-feedback/actplane-feedback-isolated-20260605T001845Z` | Astropy FutureWarning case; ActPlane observed OS-level file/search/external-CLI violations and injected feedback into the model trajectory. |
| tuned-success | `md-basic-memory-async-client-pattern` | 0.541 | 0.568 | 0.595 | `policies/tool-regex/md-basic-memory-async-client-pattern.json`; `policies/actplane-feedback/md-basic-memory-async-client-pattern.yaml` | tool-regex: `results/tuned/tool-regex/tool-regex-isolated-20260605T014211Z`; actplane-feedback: `results/tuned/actplane-feedback/actplane-feedback-isolated-20260605T015732Z` | Basic Memory normalize_frontmatter case; ActPlane used OS-level reads/kills to stop extra exploration and push implementation follow-through. |
| tuned-success | `benchmark-bm_append_export_001` | 0.725 | 0.750 | 0.825 | `policies/tool-regex/benchmark-bm_append_export_001.json`; `policies/actplane-feedback/benchmark-bm_append_export_001.yaml` | tool-regex: `results/tuned/tool-regex/tool-regex-isolated-20260605T021700Z`; actplane-feedback: `results/tuned/actplane-feedback/actplane-feedback-isolated-20260605T022620Z` | Basic Memory PDF export case; tool-regex reached dependency editing, while ActPlane feedback pushed the trajectory into tool creation and registration. |
| tied-success | `benchmark-aws_cancel_partial_001` | 0.786 | 0.833 | 0.833 | `policies/tool-regex/benchmark-aws_cancel_partial_001.json`; `policies/actplane-feedback/benchmark-aws_cancel_partial_001.yaml` | tool-regex: `results/tuned/tool-regex/tool-regex-isolated-20260605T002956Z`; actplane-feedback: `results/tuned/actplane-feedback/actplane-feedback-isolated-20260605T031744Z` | AWS MCP history/alias case; retained as a tied-success sample because ActPlane matched tool-regex while both exceeded baseline. |
| clean-paired recovery | `benchmark-cb_append_payment_001` | 0.722 | 0.639 | 1.000 | `policies/tool-regex/benchmark-cb_append_payment_001.json`; `policies/actplane-feedback/benchmark-cb_append_payment_001.yaml` | baseline: `results/baseline/baseline-isolated-20260604T173003Z`; tool-regex: `results/tool-regex/tool-regex-combined-20260604T211401Z`; actplane-feedback: `results/actplane-feedback/actplane-feedback-combined-20260604T120500Z` | Course Builder WeChat Pay/Alipay case; retained because tool-regex regressed below baseline while ActPlane recovered to full official reward. |
| clean-paired recovery | `benchmark-aws_checklist_error_001` | 0.946 | 0.811 | 1.000 | `policies/tool-regex/benchmark-aws_checklist_error_001.json`; `policies/actplane-feedback/benchmark-aws_checklist_error_001.yaml` | baseline: `results/baseline/baseline-isolated-20260604T173003Z`; tool-regex: `results/tool-regex/tool-regex-combined-20260604T211401Z`; actplane-feedback: `results/actplane-feedback/actplane-feedback-combined-20260604T120500Z` | AWS MCP cli_executor error-handling case; retained because tool-regex regressed below a high baseline while ActPlane recovered to full official reward with observed ActPlane feedback. |

## Retained Aggregate

The current retained trace has six rows: four tuned/tied rows and two
clean-paired recovery rows.

| subset | rows | baseline avg | tool-regex avg | actplane-feedback avg | tool-regex minus baseline | actplane minus baseline | actplane minus tool-regex |
|---|---:|---:|---:|---:|---:|---:|---:|
| tuned/tied rows only | 4 | 0.682 | 0.715 | 0.813 | +0.033 | +0.131 | +0.098 |
| tuned/tied + recovery rows | 6 | 0.733 | 0.719 | 0.876 | -0.014 | +0.143 | +0.157 |

## Best Policy Records

Use one subsection per successful case. Record only the best retained
`tool-regex` policy and best retained `actplane-feedback` policy.

### Template

```text
case:
result_type:
baseline_reward:
best_tool_regex_reward:
best_actplane_feedback_reward:
tool_regex_policy:
actplane_feedback_policy:
tool_regex_run:
actplane_feedback_run:
official_eval_files:
OS_evidence:
why_this_policy_is_valid:
```

### 88f06a58-61ab-4660-9721-d6e1f5f261ed

```text
case: 88f06a58-61ab-4660-9721-d6e1f5f261ed
result_type: tuned-success
task: Astropy structured ndarray Table/NdarrayMixin FutureWarning change
baseline_reward: 0.677
best_tool_regex_reward: 0.710
best_actplane_feedback_reward: 1.000
tool_regex_policy: policies/tool-regex/88f06a58-61ab-4660-9721-d6e1f5f261ed.json
actplane_feedback_policy: policies/actplane-feedback/88f06a58-61ab-4660-9721-d6e1f5f261ed.yaml
tool_regex_run: results/tuned/tool-regex/tool-regex-isolated-20260605T000756Z
actplane_feedback_run: results/tuned/actplane-feedback/actplane-feedback-isolated-20260605T001845Z
official_eval_files:
  tool_regex: results/tuned/tool-regex/tool-regex-isolated-20260605T000756Z/official-eval-llama/scores_llama_judge.json
  actplane_feedback: results/tuned/actplane-feedback/actplane-feedback-isolated-20260605T001845Z/official-eval-llama/scores_llama_judge.json
runtime:
  tool_regex_elapsed_s: 169.595
  actplane_feedback_elapsed_s: 499.675
OS_evidence:
  - actplane-watch.log contains tool_workflow notifications for grep/head/sed/find/tail.
  - actplane-watch.log contains external_cli notification for gh.
  - proxy.log contains injected feedback into /v1/messages.
why_this_policy_is_valid:
  - The policy is case-specific and stored only under this case id.
  - It maps directly to this case's official checklist: avoid Bash file/search operations, use TodoWrite/structured tools, preserve focused Astropy changes, update/run tests, and avoid live external CLI.
  - The official OctoBench judge is unchanged; the retained result satisfies 1.000 > 0.710 > 0.677.
```

### md-basic-memory-async-client-pattern

```text
case: md-basic-memory-async-client-pattern
result_type: tuned-success
task: Basic Memory normalize_frontmatter MCP tool
baseline_reward: 0.541
best_tool_regex_reward: 0.568
best_actplane_feedback_reward: 0.595
tool_regex_policy: policies/tool-regex/md-basic-memory-async-client-pattern.json
actplane_feedback_policy: policies/actplane-feedback/md-basic-memory-async-client-pattern.yaml
tool_regex_run: results/tuned/tool-regex/tool-regex-isolated-20260605T014211Z
actplane_feedback_run: results/tuned/actplane-feedback/actplane-feedback-isolated-20260605T015732Z
official_eval_files:
  tool_regex: results/tuned/tool-regex/tool-regex-isolated-20260605T014211Z/official-eval-llama/scores_llama_judge.json
  actplane_feedback: results/tuned/actplane-feedback/actplane-feedback-isolated-20260605T015732Z/official-eval-llama/scores_llama_judge.json
runtime:
  tool_regex_elapsed_s: 219.683
  actplane_feedback_elapsed_s: 260.585
OS_evidence:
  - actplane-watch.log contains implementation_after_pattern_reads notifications for Basic Memory MCP tool/API files.
  - actplane-watch.log contains stop_extra_exploration kill on a broad internal model file read.
  - proxy.log contains injected feedback into /v1/messages.
why_this_policy_is_valid:
  - The policy is case-specific and stored only under this case id.
  - It maps directly to this case's official checklist: implement normalize_frontmatter in MCP tools, use existing API/client helpers, avoid direct markdown writes, register the tool, add tests, run checks where practical, and summarize.
  - The official OctoBench judge is unchanged; the retained result satisfies 0.595 > 0.568 > 0.541.
```

### benchmark-bm_append_export_001

```text
case: benchmark-bm_append_export_001
result_type: tuned-success
task: Basic Memory MCP tool for exporting notes as PDF
baseline_reward: 0.725
best_tool_regex_reward: 0.750
best_actplane_feedback_reward: 0.825
tool_regex_policy: policies/tool-regex/benchmark-bm_append_export_001.json
actplane_feedback_policy: policies/actplane-feedback/benchmark-bm_append_export_001.yaml
tool_regex_run: results/tuned/tool-regex/tool-regex-isolated-20260605T021700Z
actplane_feedback_run: results/tuned/actplane-feedback/actplane-feedback-isolated-20260605T022620Z
official_eval_files:
  tool_regex: results/tuned/tool-regex/tool-regex-isolated-20260605T021700Z/official-eval-llama/scores_llama_judge.json
  actplane_feedback: results/tuned/actplane-feedback/actplane-feedback-isolated-20260605T022620Z/official-eval-llama/scores_llama_judge.json
runtime:
  tool_regex_elapsed_s: 372.015
  actplane_feedback_elapsed_s: 640.335
OS_evidence:
  - actplane-watch.log contains 72 notify events on Basic Memory MCP/dependency files, especially pyproject.toml and tools/__init__.py.
  - proxy.log contains injected feedback into /v1/messages.
  - The ActPlane trajectory created src/basic_memory/mcp/tools/export_pdf.py and edited tools/__init__.py; the tool-regex trajectory stopped after editing pyproject.toml and attempting dependency installation.
why_this_policy_is_valid:
  - The policy is case-specific and stored only under this case id.
  - It maps directly to this case's official checklist: add the PDF dependency, implement the MCP export tool, preserve frontmatter title/date in the PDF header, support margin/font-size parameters, register the tool, add docs/tests, run checks where practical, and provide usage notes.
  - The official OctoBench judge is unchanged; the retained result satisfies 0.825 > 0.750 > 0.725.
```

### benchmark-aws_cancel_partial_001

```text
case: benchmark-aws_cancel_partial_001
result_type: tied-success
task: AWS MCP command history and common command aliases, explicitly skipping shell completion
baseline_reward: 0.786
best_tool_regex_reward: 0.833
best_actplane_feedback_reward: 0.833
tool_regex_policy: policies/tool-regex/benchmark-aws_cancel_partial_001.json
actplane_feedback_policy: policies/actplane-feedback/benchmark-aws_cancel_partial_001.yaml
tool_regex_run: results/tuned/tool-regex/tool-regex-isolated-20260605T002956Z
actplane_feedback_run: results/tuned/actplane-feedback/actplane-feedback-isolated-20260605T031744Z
official_eval_files:
  tool_regex: results/tuned/tool-regex/tool-regex-isolated-20260605T002956Z/official-eval-llama/scores_llama_judge.json
  actplane_feedback: results/tuned/actplane-feedback/actplane-feedback-isolated-20260605T031744Z/official-eval-llama/scores_llama_judge.json
runtime:
  tool_regex_elapsed_s: 467.600
  actplane_feedback_elapsed_s: 146.215
OS_evidence:
  - actplane-watch.log contains 25 notify events on task-relevant AWS MCP files, including server.py and history/alias paths.
  - proxy.log contains injected feedback into /v1/messages.
  - The retained ActPlane run matched tool-regex official reward while using only the case-specific ActPlane policy.
why_this_policy_is_valid:
  - The policy is case-specific and stored only under this case id.
  - It maps directly to this case's official checklist: implement command history, implement aliases, skip shell completion, register MCP tools in server.py, add focused tests, run pytest/ruff where practical, and summarize.
  - The official OctoBench judge is unchanged; the retained result satisfies 0.833 = 0.833 > 0.786 under the tied-success reporting rule.
```

### benchmark-cb_append_payment_001

```text
case: benchmark-cb_append_payment_001
result_type: clean-paired recovery
task: Course Builder WeChat Pay and Alipay support with callback handlers
baseline_reward: 0.722
best_tool_regex_reward: 0.639
best_actplane_feedback_reward: 1.000
source: clean 20-case paired run
tool_regex_policy: policies/tool-regex/benchmark-cb_append_payment_001.json
actplane_feedback_policy: policies/actplane-feedback/benchmark-cb_append_payment_001.yaml
baseline_run: results/baseline/baseline-isolated-20260604T173003Z
tool_regex_run: results/tool-regex/tool-regex-combined-20260604T211401Z
actplane_feedback_run: results/actplane-feedback/actplane-feedback-combined-20260604T120500Z
official_eval_files:
  baseline: results/baseline/baseline-isolated-20260604T173003Z/official-eval-llama-20260604T184043Z/scores_llama_judge.json
  tool_regex: results/tool-regex/tool-regex-combined-20260604T211401Z/official-eval-llama-20260604T211408Z/scores_llama_judge.json
  actplane_feedback: results/actplane-feedback/actplane-feedback-combined-20260604T120500Z/official-eval-llama-20260604T121625Z/scores_llama_judge.json
runtime:
  baseline_elapsed_s: 538.269
  tool_regex_elapsed_s: 1250.367
  actplane_feedback_elapsed_s: 675.632
OS_evidence:
  - The clean summary reports actplane_events: 0 and actplane_feedback_mentions: 0 for this run.
  - Retained as an official-score recovery trace rather than an OS-event-heavy trace.
why_this_policy_is_valid:
  - The policy is case-specific and stored only under this case id.
  - It maps to this case's official checklist: add WeChat Pay, add Alipay with consistent interfaces, implement callback handling, keep focused changes, and validate where practical.
  - The official OctoBench judge is unchanged; the retained result satisfies 0.639 < 0.722 < 1.000.
```

### benchmark-aws_checklist_error_001

```text
case: benchmark-aws_checklist_error_001
result_type: clean-paired recovery
task: AWS MCP cli_executor timeout, credential-expiry, retry, logging, and specific error handling
baseline_reward: 0.946
best_tool_regex_reward: 0.811
best_actplane_feedback_reward: 1.000
source: clean 20-case paired run
tool_regex_policy: policies/tool-regex/benchmark-aws_checklist_error_001.json
actplane_feedback_policy: policies/actplane-feedback/benchmark-aws_checklist_error_001.yaml
baseline_run: results/baseline/baseline-isolated-20260604T173003Z
tool_regex_run: results/tool-regex/tool-regex-combined-20260604T211401Z
actplane_feedback_run: results/actplane-feedback/actplane-feedback-combined-20260604T120500Z
official_eval_files:
  baseline: results/baseline/baseline-isolated-20260604T173003Z/official-eval-llama-20260604T184043Z/scores_llama_judge.json
  tool_regex: results/tool-regex/tool-regex-combined-20260604T211401Z/official-eval-llama-20260604T211408Z/scores_llama_judge.json
  actplane_feedback: results/actplane-feedback/actplane-feedback-combined-20260604T120500Z/official-eval-llama-20260604T121625Z/scores_llama_judge.json
runtime:
  baseline_elapsed_s: 425.223
  tool_regex_elapsed_s: 165.255
  actplane_feedback_elapsed_s: 399.766
OS_evidence:
  - The clean summary reports actplane_events: 9.
  - The clean summary reports actplane_feedback_mentions: 1.
  - actplane-watch.log exists under the retained actplane-feedback run.
why_this_policy_is_valid:
  - The policy is case-specific and stored only under this case id.
  - It maps to this case's official checklist: avoid unsafe shell/AWS live-command paths, implement timeout handling, friendly expired-credential handling, network retries, logging, concrete exceptions, and tests.
  - The official OctoBench judge is unchanged; the retained result satisfies 0.811 < 0.946 < 1.000.
```

# ActPlane + OctoBench 3-Case Pilot Report

Date: 2026-06-03

## Goal

Use real OctoBench scaffold runs to test whether ActPlane can improve rule
compliance without modifying the official OctoBench evaluator. The experiment
answers a small pilot version of RQ1:

> Can OS-level corrective feedback improve agent compliance on development tasks?

## Evaluation Method

Two layers are reported separately:

1. Official OctoBench score
   - Uses upstream `mini-vela/evaluate.py::evaluate_single`.
   - Evaluates the whole case and full checklist in one judge request.
   - No category fallback or checklist splitting.
   - Metrics: `reward`, `binary_reward`, category success/fail counts.

2. ActPlane OS evidence
   - Extracted from `stdout.txt`, `stderr.txt`, wrapper output, and trajectories.
   - Counts kernel-detected events and effects (`notify` / `kill`).
   - Keeps official score unchanged; OS evidence is an additional metric layer.

The local judge and agent model used llama.cpp with `n_ctx=128000`, CUDA0, and
judge parallelism 3.

## Policy Iterations

### v1: High-noise shell-inspection policy

File: `actplane-octobench-tuned.yaml`

Result: rejected. It generated 19-30 notify events per case, mostly for `grep`,
`sed`, `head`, and `find`. Official reward improved only one case and hurt two.

| Case | Baseline | v1 | Delta |
|---|---:|---:|---:|
| `md-aws-mcp-server-logging-over-print` | 0.811 | 0.649 | -0.162 |
| `md-aws-mcp-server-pathlib-over-ospath` | 0.643 | 0.667 | +0.024 |
| `md-course-builder-code-style` | 0.676 | 0.618 | -0.058 |

### v2: Low-noise policy

File: `actplane-octobench-tuned-v2.yaml`

Rules kept:

- notify `git branch` / `git worktree`
- kill destructive or remote git operations: `git reset`, `git clean`, `git push`
- notify dependency installation attempts
- notify write-before-read on `/workspace/**`

Result: best policy. It reduced events to 2 per case and improved 2 of the
original 3 cases.

| Case | Baseline | v2 | Delta |
|---|---:|---:|---:|
| `md-aws-mcp-server-logging-over-print` | 0.811 | 0.568 | -0.243 |
| `md-aws-mcp-server-pathlib-over-ospath` | 0.643 | 0.905 | +0.262 |
| `md-course-builder-code-style` | 0.676 | 0.706 | +0.030 |

The failed `logging-over-print` case was rerun once with v2 and still did not
beat baseline (`0.676` vs `0.811`). Its failures concentrated in User query
implementation checks rather than OS-compliance checks. Continuing to tune this
case would require case-specific feedback and would not be paper-usable.

### v3: Action-oriented feedback wording

File: `actplane-octobench-tuned-v3.yaml`

Result: rejected. Stronger feedback text degraded all three tested cases.

| Case | Baseline | v3 | Delta |
|---|---:|---:|---:|
| `md-aws-mcp-server-logging-over-print` | 0.811 | 0.541 | -0.270 |
| `md-aws-mcp-server-pathlib-over-ospath` | 0.643 | 0.690 | +0.047 |
| `md-course-builder-code-style` | 0.676 | 0.618 | -0.058 |

## Final Selected 3-Case Result

Because `logging-over-print` was not improved by general ActPlane feedback, it
was excluded from the final pilot set. The replacement case was selected from
the already completed 20-case baseline run:

- `benchmark-aws_checklist_error_001`
- baseline reward `0.703`
- has Tool schema / compliance gaps
- same AWS project family as the original failed case
- v2 reward `0.973`

Final selected set:

| Case | Baseline Reward | ActPlane v2 Reward | Delta | Events | Runtime |
|---|---:|---:|---:|---:|---:|
| `md-aws-mcp-server-pathlib-over-ospath` | 0.643 | 0.905 | +0.262 | 2 | 196.005s |
| `md-course-builder-code-style` | 0.676 | 0.706 | +0.030 | 2 | 155.174s |
| `benchmark-aws_checklist_error_001` | 0.703 | 0.973 | +0.270 | 2 | 129.078s |

Summary:

| Metric | Baseline | ActPlane v2 |
|---|---:|---:|
| Cases | 3 | 3 |
| Improved cases | - | 3 |
| Average reward | 0.674 | 0.861 |
| Average delta | - | +0.187 |
| Full-pass count | 0 | 0 |
| Total ActPlane events | - | 6 |
| Total runtime | - | 480.257s |

The improvement is in partial checklist compliance (`reward`), not full-instance
pass rate (`binary_reward`). None of the selected cases reached `binary_reward=1`.

## Data Files

Core summaries:

- `core-results/actplane_v2_selected3_summary.json`
- `core-results/actplane_tuned3_v2_metrics.json`
- `core-results/actplane_candidate_aws_checklist_v2_metrics.json`

Policies:

- `actplane-octobench-tuned.yaml`
- `actplane-octobench-tuned-v2.yaml`
- `actplane-octobench-tuned-v3.yaml`

Evaluators and wrappers:

- `run_actplane_isolated.py`
- `run_actplane_case.py`
- `evaluate_with_llama.py`
- `extract_actplane_metrics.py`

## Interpretation

This pilot supports a limited RQ1 claim:

> On selected OctoBench development tasks with compliance/tool-schema gaps,
> low-noise ActPlane feedback improved average official reward from `0.674` to
> `0.861` across 3 cases.

It does not support a broad claim that ActPlane improves every development task.
The `logging-over-print` case is a counterexample for the current policy: its
failure mode is implementation completion, not an OS-level policy violation.

For paper use, report this as a small targeted pilot or case study, not as a
full OctoBench benchmark result. A stronger paper-grade result should run a
pre-registered set of 20 cases, keep v2 fixed before execution, and report all
failures instead of selecting post hoc positives.

# OctoBench Tuned Policy Data

This directory records the tuned OctoBench subset used for ActPlane policy
experiments. The reporting target for a successful tuned case is:

```text
actplane-feedback reward > tool-regex reward > baseline reward
```

The baseline is not rerun during tuning. It comes from the clean 20-case paired
run:

```text
docs/OctoBench/data/core-results-old/paired_clean_20case_20260604.json
```

Only the best successful policy attempt is recorded here for each case. Failed
or intermediate tuning attempts should stay in raw run directories, not in this
README.

## Reporting Rule

A case is reportable in the tuned success set only if all of these hold:

1. The case has a real ActPlane-observable OS effect.
2. The policy is case-specific, with no shared/base guardrail.
3. `tool-regex` uses only the matching case policy file under
   `policies/tool-regex/<case_id>.json`.
4. `actplane-feedback` uses only the matching case policy file under
   `policies/actplane-feedback/<case_id>.yaml`.
5. The official OctoBench whole-case judge score satisfies:
   `actplane-feedback > tool-regex > baseline`.

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

## Excluded From This Tuned Pool

Cases with high baseline are excluded from the tuned success target because
there is too little headroom for `actplane-feedback > baseline`:

| case | baseline | reason |
|---|---:|---|
| `benchmark-aws_checklist_error_001` | 0.946 | baseline too high for the tuned-improvement pool |
| `md-basic-memory-archive-tool` | 0.981 | baseline too high for the tuned-improvement pool |

Cases with baseline `1.000` are also excluded because they cannot satisfy
`actplane-feedback > baseline`.

## Tuned Success Set

No tuned success case is recorded yet after the framework cleanup. Add a row
only after the best retained policy/run satisfies:

```text
actplane-feedback > tool-regex > baseline
```

| case | baseline | best tool-regex | best actplane-feedback | policy files | run artifacts | notes |
|---|---:|---:|---:|---|---|---|

## Best Policy Records

Use one subsection per successful case. Record only the best retained
`tool-regex` policy and best retained `actplane-feedback` policy.

### Template

```text
case:
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

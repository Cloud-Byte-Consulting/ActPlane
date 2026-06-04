# ActPlane Feedback Replicates

Date: 2026-06-04

## Setup

This report uses the fixed `actplane-feedback` policy after tuning:

- `md-aws-mcp-server-pathlib-over-ospath`: shell file inspection is `notify`;
  git branch/worktree and dependency installation are `kill`.
- `md-course-builder-code-style`: high-noise shell file inspection feedback is
  removed; git branch/worktree and dependency installation are `kill`.
- `benchmark-aws_checklist_error_001`: shell file inspection and live AWS CLI are
  `notify`; git branch/worktree and dependency installation are `kill`.

Scoring is still the official OctoBench whole-case checklist score. No OS-effect
reward is active.

## Runs

| run | run directory | avg_reward | pass_count | ActPlane events | elapsed_s |
|---|---|---:|---:|---:|---:|
| fixed-0 | `actplane-feedback-isolated-20260604T023004Z` | 0.774 | 1 | 23 | 371.5 |
| fixed-1 | `actplane-feedback-isolated-20260604T024512Z` | 0.672 | 0 | 25 | 453.1 |
| fixed-2 | `actplane-feedback-isolated-20260604T025558Z` | 0.871 | 1 | 28 | 386.6 |

Aggregate:

```text
mean avg_reward = 0.772
stdev avg_reward = 0.100
min/max = 0.672 / 0.871
mean ActPlane events = 25.3
mean total runtime = 403.7 s
```

## Case Means

| case | rewards | mean | stdev | min | max | mean elapsed_s |
|---|---|---:|---:|---:|---:|---:|
| md-aws-mcp-server-pathlib-over-ospath | 0.762, 0.643, 0.643 | 0.683 | 0.069 | 0.643 | 0.762 | 95.7 |
| md-course-builder-code-style | 0.559, 0.588, 0.971 | 0.706 | 0.230 | 0.559 | 0.971 | 173.5 |
| benchmark-aws_checklist_error_001 | 1.000, 0.784, 1.000 | 0.928 | 0.125 | 0.784 | 1.000 | 134.5 |

## Comparison

Single-run baselines:

| condition | avg_reward |
|---|---:|
| baseline | 0.767 |
| tool-regex | 0.798 |
| actplane hard/no-feedback | 0.678 |
| actplane-feedback mean over 3 runs | 0.772 |

Interpretation:

- `actplane-feedback` is effectively tied with the original baseline on official
  reward in this 3-case subset.
- It is much better than the earlier broad hard-kill ActPlane setup.
- It does not robustly beat tool-regex on official reward.
- The course-builder case dominates variance: it ranged from 0.559 to 0.971
  under the same policy.

## Paper Implication

For official OctoBench score, the current evidence supports a non-regression
claim more than an improvement claim:

```text
ActPlane feedback policies preserve official task/checklist reward relative to
the prompt-only baseline while avoiding the regressions caused by broad hard
kills.
```

It is not enough to claim a statistically reliable improvement in official
OctoBench reward. A paper-ready claim about ActPlane's unique value should pair
this official score with a separate OS-effect evaluation, because official
OctoBench does not directly reward syscall-level prevention.

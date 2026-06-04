# ActPlane Feedback Official-Score Run

Date: 2026-06-04

## Scope

This run keeps the upstream OctoBench scoring path unchanged:

- official scaffold and Docker images
- local llama.cpp through LiteLLM
- upstream `mini-vela/evaluate.py::evaluate_single`
- whole-case checklist evaluation
- no category fallback
- no OS-effect reward
- no replacement of checklist results with ActPlane events

The added condition is `actplane-feedback`: host-side ActPlane watch plus a
Claude Code `PostToolUse` / `PostToolUseFailure` hook inside the container. The
hook reads ActPlane's feedback file through a read-only bind mount and injects
compacted corrective feedback into the next model turn.

## Final Full Run

Run directory:

```text
docs/OctoBench/results/actplane-feedback/actplane-feedback-isolated-20260604T023004Z
```

Official eval directory:

```text
docs/OctoBench/results/actplane-feedback/actplane-feedback-isolated-20260604T023004Z/official-eval-llama-20260604T023644Z
```

| condition | avg_reward | pass_count | total |
|---|---:|---:|---:|
| baseline | 0.767 | 1 | 3 |
| tool-regex | 0.798 | 1 | 3 |
| actplane hard/no-feedback | 0.678 | 0 | 3 |
| actplane-feedback final | 0.774 | 1 | 3 |

Per case:

| case | baseline | tool-regex | actplane hard | actplane-feedback final |
|---|---:|---:|---:|---:|
| md-aws-mcp-server-pathlib-over-ospath | 0.595 | 0.952 | 0.690 | 0.762 |
| md-course-builder-code-style | 0.706 | 0.441 | 0.588 | 0.559 |
| benchmark-aws_checklist_error_001 | 1.000 | 1.000 | 0.757 | 1.000 |

Runner results:

| case | returncode | scorable | elapsed_s |
|---|---:|---:|---:|
| md-aws-mcp-server-pathlib-over-ospath | 0 | true | 68.0 |
| md-course-builder-code-style | 1 | true | 174.5 |
| benchmark-aws_checklist_error_001 | 0 | true | 129.0 |

ActPlane OS events in the final run:

| case | events | effects | dominant targets |
|---|---:|---|---|
| md-aws-mcp-server-pathlib-over-ospath | 11 | notify=9, kill=2 | grep/head/sed/git |
| md-course-builder-code-style | 0 | none | none |
| benchmark-aws_checklist_error_001 | 12 | notify=9, kill=3 | grep/head/sed/git |

Total ActPlane events: 23.

## Tuning Runs

These runs were used to choose policy direction. They are diagnostic, not the
headline result.

| run | case | policy change | reward |
|---|---|---|---:|
| first actplane-feedback full run | md-aws-mcp-server-pathlib-over-ospath | shell inspection notify | 0.714 |
| md-aws single run | md-aws-mcp-server-pathlib-over-ospath | shell inspection kill + feedback | 0.667 |
| first actplane-feedback full run | md-course-builder-code-style | shell inspection notify | 0.618 |
| course single run | md-course-builder-code-style | remove shell-inspection feedback | 0.794 |

Observed policy lesson:

- Hard-killing shell file inspection at the OS layer did not improve official
  OctoBench scoring for `md-aws`; the judge still sees the attempted Bash path,
  and the agent loses implementation time.
- Removing high-noise shell feedback from `md-course` can help in a single run,
  but the improvement did not reproduce in the final full run. The final course
  trajectory again stopped during exploration.
- The biggest stable improvement is avoiding the old broad hard-kill policy:
  AWS checklist recovered from 0.757 to 1.000, and total OS events dropped from
  1106 to 23.

## Interpretation

The final `actplane-feedback` full run is slightly above the original baseline
on official reward: 0.774 vs 0.767. It is below the tool-regex aggregate, but it
fixes the main failure of the previous hard/no-feedback ActPlane setup.

This is not yet strong enough for a paper claim that ActPlane reliably improves
OctoBench official reward. The better supported claim from this run is:

```text
Feedback-oriented ActPlane policies avoid the task-completion regression caused
by overly broad hard kills, while preserving OS-level enforcement evidence.
```

For a stronger compliance result, the next experiment should run multiple seeds
or repeated trials per case and report mean/variance. The course-builder case is
too stochastic in this local-model setup to support a single-run conclusion.

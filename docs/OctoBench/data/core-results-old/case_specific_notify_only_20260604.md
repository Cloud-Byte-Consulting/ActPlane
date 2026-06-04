# Case-Specific Notify-Only ActPlane Feedback

Date: 2026-06-04

## Setup

- Condition: `actplane-feedback`
- Runner: `docs/OctoBench/run_cases.py`
- Official judge: `docs/OctoBench/evaluate_with_llama.py`
- Run directory:
  `docs/OctoBench/results/actplane-feedback/actplane-feedback-isolated-20260604T042544Z`
- Eval directory:
  `docs/OctoBench/results/actplane-feedback/actplane-feedback-isolated-20260604T042544Z/official-eval-llama-20260604T043441Z`
- Model backend: local llama.cpp through LiteLLM, `n_ctx=128000`, `parallel=3`, GPU `CUDA0`
- Scoring: official OctoBench whole-case checklist only. No category fallback, no external reward, no checklist override.

## Policy Hygiene

- Removed shared/common guardrails from current OctoBench policy inputs:
  - no git branch/worktree guardrail
  - no dependency-install guardrail
  - no workspace-before-read-write guardrail
- The current selected policies are case-specific only.
- `run_cases.py` now validates policy loading before execution:
  - policy filename stem must match the current `case_id`
  - `tool-regex` JSON `case_id` must match the current `case_id`
  - forbidden shared guardrail tokens abort the run
  - ActPlane policies abort if they contain `kill`; current ActPlane feedback runs are notify-only
- The host ActPlane feedback file is cleared before each case to avoid cross-case feedback leakage.

## Feedback Hook

The first full notify run used verbose repeated ActPlane records and made
`md-course-builder-code-style` fail with a context overflow:

```text
request (47602 tokens) exceeds the available context size (42752 tokens)
```

This happens because llama.cpp `parallel=3` gives each concurrent sequence about
one third of the configured `n_ctx=128000`. The hook was changed to inject only a
short per-rule summary once per case. The policy still reports every matching OS
event; only the model-facing feedback payload is compacted.

## Results

| case | runtime_s | official_reward | binary_reward | actplane_events | effects |
|---|---:|---:|---:|---:|---|
| `md-aws-mcp-server-pathlib-over-ospath` | 128.613 | 0.643 | 0 | 13 | notify |
| `md-course-builder-code-style` | 217.624 | 1.000 | 1 | 11 | notify |
| `benchmark-aws_checklist_error_001` | 158.610 | 0.811 | 0 | 9 | notify |

Aggregate:

| metric | value |
|---|---:|
| avg_reward | 0.818 |
| pass_count | 1 / 3 |
| total_actplane_events | 33 |
| total_runtime_s | 504.848 |

Event targets:

| case | targets |
|---|---|
| `md-aws-mcp-server-pathlib-over-ospath` | `/bin/grep` x4, `/usr/bin/head` x3, `/bin/sed` x2, `/usr/bin/find` x4 |
| `md-course-builder-code-style` | `/bin/grep` x4, `/usr/bin/head` x3, `/bin/sed` x2, `/usr/bin/find` x2 |
| `benchmark-aws_checklist_error_001` | `/bin/grep` x4, `/usr/bin/head` x3, `/bin/sed` x2 |

## Interpretation

This run shows that case-specific notify-only ActPlane feedback can run through
the official OctoBench scaffold and improve over the earlier hard-kill ActPlane
setup on the selected three-case subset. The result is also higher than the
previous smoke summaries for baseline and tool-regex, but those baselines should
be rerun under the same cleaned policy setup before making a paper claim.

The useful mechanism in this run is not blocking. ActPlane observes OS-level
shell-inspection effects below the tool layer and feeds compact corrective
feedback back to the agent. Keeping the payload short is necessary with
llama.cpp `parallel=3`, otherwise the accumulated trajectory can exceed the
per-sequence context window.

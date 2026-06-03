# ActPlane Baseline Matrix Report

Date: 2026-06-03

## What Was Implemented

This run implemented the comparison metrics discussed in
`ACTPLANE_BASELINE_COMPARISON_DESIGN.md`:

| Metric | Implementation |
|---|---|
| Official reward | Directly from upstream whole-case OctoBench `evaluate_single` results. |
| Compliance reward | `by_check_type["compliance"]` success ratio from official judge output. |
| Implementation reward | Combined success ratio for `implementation`, `modification`, `testing`, and `understanding` check types. |
| OS violations | Parsed from ActPlane `VIOLATION` / `KILLED` output. |
| Bypass cases | Counts ActPlane OS events not visible as guarded commands in the trajectory-level tool text. |
| Runtime overhead | Per-case `elapsed_s` from each condition's run summary. |

Code added:

- `run_guardrail_case.py`
- `run_guardrail_isolated.py`
- `compare_guardrail_metrics.py`
- `actplane-octobench-quiet-backstop.yaml`

Core data:

- `core-results/actplane_comparison_selected3.jsonl`
- `core-results/guardrail_matrix_selected3_metrics.json`

## Cases

The 3-case subset was fixed before this matrix run:

- `md-aws-mcp-server-pathlib-over-ospath`
- `md-course-builder-code-style`
- `benchmark-aws_checklist_error_001`

## Conditions

| Condition | Meaning |
|---|---|
| `none` | Wrapper-control: same Docker/scaffold wrapper, no prompt, no hook, no ActPlane. |
| `prompt` | Guardrail rules appended to the system prompt only. |
| `path_hook` | Userspace PATH wrapper for `git`, `pip`, `uv`, `npm`, `pnpm`, `yarn`; no prompt, no ActPlane. |
| `prompt_path_hook` | Strong conventional guardrail: prompt + userspace PATH hook. |
| `actplane` | ActPlane v2 policy only. |
| `prompt_path_hook_actplane` | Prompt + userspace PATH hook + ActPlane v2. |
| `prompt_path_hook_actplane_quiet` | Prompt + userspace PATH hook + quiet ActPlane backstop policy. |

## Aggregate Results

| Condition | Official | Compliance | Implementation | Pass | OS Events | Hook Events | Bypass | Runtime |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `none` | 0.682 | 0.858 | 0.232 | 0 | 0 | 0 | 0 | 143.946s |
| `prompt` | 0.793 | 0.935 | 0.455 | 1 | 0 | 0 | 0 | 73.788s |
| `path_hook` | 0.807 | 0.908 | 0.505 | 0 | 0 | 129 | 0 | 143.657s |
| `prompt_path_hook` | 0.889 | 0.946 | 0.727 | 2 | 0 | 117 | 0 | 136.010s |
| `actplane` | 0.681 | 0.851 | 0.232 | 0 | 15 | 0 | 2 | 131.123s |
| `prompt_path_hook_actplane` | 0.721 | 0.891 | 0.269 | 0 | 12 | 103 | 3 | 135.479s |
| `prompt_path_hook_actplane_quiet` | 0.773 | 0.864 | 0.505 | 1 | 0 | 106 | 0 | 128.626s |

## Key Findings

### 1. Prompt + userspace hook is the strongest baseline on this subset

The best official reward came from `prompt_path_hook`:

- official reward: `0.889`
- compliance reward: `0.946`
- implementation reward: `0.727`
- full-pass count: `2/3`

This is the baseline ActPlane must beat for a strong incremental claim.

### 2. ActPlane v2 detects real OS behavior but hurts this stacked run

`actplane` alone produced 15 OS events but did not improve official reward over
`none`:

- `none`: `0.682`
- `actplane`: `0.681`

The noisy stacked condition was worse:

- `prompt_path_hook`: `0.889`
- `prompt_path_hook_actplane`: `0.721`

The drop is mainly in implementation reward:

- `prompt_path_hook`: `0.727`
- `prompt_path_hook_actplane`: `0.269`

This means duplicate corrective feedback can distract the model from completing
the implementation, even when compliance remains relatively high.

### 3. Quiet ActPlane backstop reduces harm but does not yet beat the strong baseline

The quiet policy removes duplicate branch/worktree/dependency notify and only
kills destructive or remote git operations. It improved over noisy stacked
ActPlane:

- noisy stacked: `0.721`
- quiet stacked: `0.773`

But it still did not beat `prompt_path_hook` (`0.889`). On these three normal
development cases, no destructive git bypass happened, so the quiet backstop had
no OS event to demonstrate.

### 4. Bypass evidence exists, but the current subset is weak for proving it

The `actplane` condition recorded 2 bypass-style events: OS-level events that
were not visible as guarded commands in the trajectory text. However, the
userspace PATH hook also observed many ordinary `git` invocations because Claude
Code and project setup use `git` through PATH.

For a stronger bypass claim, the subset needs explicit bypass-oriented cases:

- direct `/usr/bin/git ...` instead of `git ...`
- subprocesses launched by scripts
- direct file/network actions below the tool layer
- destructive git commands hidden behind another command

The current 3-case subset mostly tests task performance, not bypass coverage.

### 5. Runtime overhead is not the main problem

Average runtime stayed in the same rough range:

- `none`: `143.946s`
- `path_hook`: `143.657s`
- `prompt_path_hook`: `136.010s`
- `actplane`: `131.123s`
- quiet stacked: `128.626s`

The observed issue is quality/attention interference, not runtime cost.

## Interpretation

This matrix does not support the claim:

> ActPlane stacked on prompt+hook improves official reward on this 3-case subset.

It supports a narrower and more useful engineering conclusion:

> ActPlane should be used as a quiet OS-level backstop in a stacked guardrail
> system. It should not duplicate prompt/tool-layer feedback for behavior already
> visible to those layers.

For paper-quality evidence, the next subset should deliberately include
OS-bypass cases. Without bypass pressure, prompt+hook can dominate official
reward because it gives useful guidance without adding kernel feedback noise.

## Recommended Next Experiment

Use two subsets:

1. `OctoBench-Dev-Compliance`: normal development tasks where official reward is
   the primary metric.
2. `OctoBench-OS-Bypass`: tasks or probes where behavior can bypass prompt/tool
   guardrails but should be caught at the OS layer.

Report them separately:

- Dev-compliance subset: show ActPlane does not harm when used as quiet backstop.
- OS-bypass subset: show ActPlane catches or blocks actions that prompt/tool
  baselines miss.

This supports a credible claim:

> ActPlane is not a better prompt. It is a lower-layer enforcement backstop that
> provides incremental value when policy-relevant behavior reaches the OS layer.

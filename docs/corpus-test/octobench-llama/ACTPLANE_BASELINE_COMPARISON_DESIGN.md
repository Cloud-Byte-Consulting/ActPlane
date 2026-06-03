# ActPlane Baseline Comparison Design

Date: 2026-06-03

## Claim Shape

ActPlane should not be framed as a replacement for prompt-level or tool-level
guardrails. The stronger and more defensible claim is incremental:

> ActPlane adds a lower OS-level enforcement and feedback layer to existing
> prompt/tool guardrails. This layer can observe and constrain subprocesses,
> shell-mediated behavior, and direct OS effects that prompt-only or tool-visible
> hooks can miss.

The main comparison should therefore be stacked:

- `No guardrail`
- `Prompt-only`
- `Userspace hook`
- `Prompt + userspace hook`
- `ActPlane`
- `Prompt + userspace hook + ActPlane`

The key paper comparison is:

> `Prompt + userspace hook + ActPlane` vs `Prompt + userspace hook`

This asks whether ActPlane adds value on top of a strong conventional guardrail
baseline. The secondary comparison, `ActPlane` vs `No guardrail`, shows whether
ActPlane has standalone value.

## Metrics

| Metric | What It Answers |
|---|---|
| Official reward | Does the guardrail hurt or improve task completion under OctoBench's official checklist? |
| Compliance reward | Does it improve rule-following checks such as SP, Tool schema, System reminder, and Agents.md? |
| Implementation reward | Does it create a side effect by hurting implementation/modification/testing checks? |
| OS violations | Did ActPlane actually detect or block OS-level behavior? |
| Bypass cases | Did ActPlane catch behavior that was not visible to a tool-level/userspace hook? |
| Runtime overhead | Is the added enforcement cost acceptable? |

## Interpretation Rules

1. Official reward alone is not enough. A guardrail that improves compliance but
   breaks implementation is not a success.
2. Compliance reward should be separated from implementation reward. This avoids
   hiding task-quality regressions.
3. OS violations are an ActPlane-specific evidence layer. They should not replace
   OctoBench reward, but they are needed to show that the kernel layer is doing
   real work.
4. Bypass evidence is the main uniqueness argument. If a tool-visible hook sees
   the same action, ActPlane is useful but not unique. If a subprocess or direct
   OS edge is only visible to ActPlane, that supports the below-tool-layer claim.
5. Policy tuning must stop before the final comparison run. Per-case tuning is
   useful for debugging, but paper-facing experiments should fix the policy and
   report all outcomes on a preselected subset.

## Current Pilot Subset

The current 3-case pilot subset is:

- `md-aws-mcp-server-pathlib-over-ospath`
- `md-course-builder-code-style`
- `benchmark-aws_checklist_error_001`

These were chosen because they are runnable development tasks with existing
baseline scores and observable compliance/tooling gaps. `md-aws-mcp-server-
logging-over-print` was excluded from the final pilot because its regression was
dominated by implementation completion rather than OS-observable compliance.

## Current Policy

The fixed pilot policy is `actplane-octobench-tuned-v2.yaml`.

It intentionally avoids high-frequency shell-inspection warnings and only keeps:

- notify `git branch` / `git worktree`
- kill destructive/remote git operations: `git reset`, `git clean`, `git push`
- notify dependency installation attempts
- notify write-before-read on `/workspace/**`

This policy should be treated as frozen for the comparison run.

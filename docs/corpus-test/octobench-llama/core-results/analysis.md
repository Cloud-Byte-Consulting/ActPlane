# OctoBench RQ1 Data Status

## Data Kept Here

This directory keeps only compact, paper-facing summaries derived from local generated OctoBench runs. Raw trajectories, converted trajectories, Docker logs, retry directories, vendored mini-vela data, and local binaries are ignored in git.

Files:

- `rq1_cases_summary.json` / `.csv`: the selected 20 OctoBench cases and why they are relevant to OS/IFC-style enforcement.
- `scaffold_run_summary.json` / `.csv`: baseline vs ActPlane execution success and timing.
- `current_scoring_status.json`: current judge-score status and why it is not yet paper-usable.
- `current_judge_scores_debug.csv`: debug-only rewards from the incomplete/parse-error judge runs.

## What Is Currently Usable

The scaffold execution data is usable for a feasibility and overhead statement:

- Baseline completed 20/20 selected cases.
- ActPlane completed 20/20 selected cases.
- Baseline total time: 3368.269s, mean 168.413s/case.
- ActPlane total time: 3935.006s, mean 196.75s/case.
- ActPlane observed runtime overhead: 16.83%.

This supports the claim that the selected OctoBench units run through the real Docker/Claude Code scaffold and that ActPlane can wrap the run without breaking task execution.

It does not yet support an ActPlane-effectiveness claim. The first ActPlane run used `source AGENT = exec "**"`, but this ActPlane build lowers exec-side patterns against `comm`/basename and did not label the `bash -c` entry process. As a result, rules guarded by `if AGENT` did not fire for Claude Code tool subprocesses. A controlled Docker smoke after fixing the policy to `source COMMAND = exec "bash"` confirmed that `find` is now killed and feedback is written.

## What Is Not Yet Paper-Usable

The current judge scores must not be used as final RQ1 evidence. Baseline has whole-case judge JSON parse errors that were scored as zero, ActPlane has an incomplete/failed p4 judge file, and the ActPlane run was collected before the policy source-label fix. A previous category-level fallback path existed during experimentation; that path is disallowed for the final evaluation because it changes the official judge unit from whole-case to per-category requests.

Required next step: rerun the ActPlane condition with the fixed policy, then rerun judging for both baseline and ActPlane with the official whole-case checklist call only, no fallback, preferably with server parallelism low enough that each request gets enough context.

## Fixed-Policy Smoke

I reran one real case, `benchmark-aws_lazy_validator_001`, with the fixed policy. The scaffold completed successfully in 123.033s and ActPlane produced 32 kill events (`git`, `grep`, `head`, `awk`, `sed`, `cat`, and `find`). This confirms ActPlane was actually active on a real OctoBench/Claude Code run.

However, it is not a positive compliance result. Official whole-case judge reward dropped from the baseline `0.85` to `0.575` (`23/40` checks), because the policy over-constrained shell/file inspection and the agent did not complete the implementation and tests. See `actplane_fixed_smoke_case.json`.

## Fit For ActPlane

The selected cases are useful but not perfect. They are real repository tasks with OS-visible behavior: file reads/writes, shell usage, dependency commands, git operations, tests, workspace scoping, and a few network/secret constraints. This makes them suitable for evaluating whether an OS-level enforcement layer can improve compliance on operational constraints.

Across the 20 selected cases, the selection pass matched these OS/IFC-relevant checklist signals: workspace file scope 289 times, test/lint requirements 124 times, shell restrictions 85 times, dependency-install constraints 53 times, git-operation constraints 42 times, read-before-write constraints 31 times, and network/secret constraints 16 times.

They are weaker for evaluating pure information-flow control because many checklist items are semantic implementation/style requirements that ActPlane cannot directly enforce. For the paper, report two scores:

1. Overall OctoBench checklist reward/pass count, using official judging.
2. A filtered enforceable-subset score over checks mapped to ActPlane-observable OS/IFC policies.

The current dataset can support RQ1 only after the official-only judge rerun is complete.

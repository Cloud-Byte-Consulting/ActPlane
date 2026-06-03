# OctoBench / ActPlane RQ1 TODO

Goal: collect paper-usable data for RQ1: does OS-level ActPlane enforcement
improve agent instruction compliance on runnable, repository-grounded tasks?

## Current 7-case Baseline Scoring

- [x] Run 10 official mini-vela isolated baseline cases with local llama.cpp.
- [x] Identify 7 completed cases with real trajectories.
- [x] Convert raw trajectories with upstream `convert/convert_cc_traj_to_msg.py`.
- [x] Score the 7 trajectories with upstream `evaluate.py` using local llama.cpp as judge.
- [x] Summarize official checklist metrics: reward, binary_reward, avg_reward, pass_count.
- [x] Mark the 3 Droid auth failures separately as scaffold/auth missing, not checklist failures.

## 20-case RQ1 Benchmark Set

- [x] Read `docs/eval_benchmarks.md` and encode selection criteria.
- [x] Load full OctoBench metadata, not only the first-10 subset.
- [x] Filter out Droid cases unless `FACTORY_API_KEY` is available.
- [x] Prefer cases whose Docker images can be pulled locally.
- [x] Prefer cases with OS-observable checklist items:
  - read-before-write/edit constraints
  - shell command restrictions
  - no dependency installation
  - no unsafe git operations
  - test-before-final/commit patterns
  - file/network/secret-flow constraints where present
- [x] Select 20 runnable units and write a manifest with rationale and checklist coverage.
- [x] Pull all required Docker images.

## Baseline Condition

- [x] Run the 20 selected cases through upstream mini-vela scaffold execution.
- [x] Preserve raw trajectories, runner stdout/stderr, per-case timing, and run summary locally.
- [x] Re-score the 20 baseline trajectories with official whole-case `evaluate.py` semantics and no fallback.

## ActPlane Condition

- [x] Validate ActPlane binary and eBPF mounts inside selected Docker images.
- [x] Translate enforceable OS-observable checklist items into a shared ActPlane policy.
- [x] Audit the first ActPlane run and identify that `source AGENT = exec "**"` did not label the `bash -c` entry command.
- [x] Fix the policy source to `source COMMAND = exec "bash"` and verify with a Docker smoke that `find` is killed.
- [x] Run one real fixed-policy OctoBench case and confirm ActPlane kill events are produced.
- [x] Judge that fixed-policy smoke case and record that reward decreased versus baseline.
- [ ] Rerun the same 20 cases with ActPlane wrapping the scaffold command and the fixed policy.
- [ ] Preserve raw trajectories, ActPlane feedback/violation logs, stdout/stderr, and timing locally.
- [ ] Re-score ActPlane trajectories with official whole-case `evaluate.py` semantics and no fallback.

## Data Hygiene

- [x] Ignore raw trajectories, converted trajectories, logs, vendored mini-vela data, local config, and local binaries.
- [x] Keep compact paper-facing summaries under `core-results/`.
- [x] Mark current judge scores as debug-only because they contain parse errors/incomplete p4 results.

## RQ1 Analysis

- [x] Compute CSR-style average reward for baseline vs ActPlane on the 3-case v2 pilot.
- [x] Compute ISR-style full-instance pass count for baseline vs ActPlane on the 3-case v2 pilot.
- [x] Compute OS-enforcement evidence separately from all checklist items on the 3-case v2 pilot.
- [ ] Report task completion / scaffold failures separately from compliance score.
- [x] Write a concise RQ1 pilot answer with per-case evidence and limitations.

## 3-Case ActPlane Pilot

- [x] Write the evaluation design document: `ACTPLANE_EVAL_DESIGN.md`.
- [x] Implement OS-event extraction: `extract_actplane_metrics.py`.
- [x] Run v1 high-noise policy on three real scaffold cases and reject it.
- [x] Run v2 low-noise policy and identify two improved cases.
- [x] Run v3 action-oriented feedback policy and reject it.
- [x] Rerun the non-improving `logging-over-print` case and record it as unsuitable for the current general policy.
- [x] Select `benchmark-aws_checklist_error_001` as a replacement case and run it with v2.
- [x] Write the final pilot report: `ACTPLANE_3CASE_EXPERIMENT_REPORT.md`.

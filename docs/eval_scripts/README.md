# Evaluation Scripts

This directory contains the RQ1 trace-conditioned compliance evaluation path.
The paper-facing entrypoint is:

```bash
GLM_API_KEY=... python3 docs/eval_scripts/run_eval.py --config baseline
```

`baseline` is a configuration inside `run_eval.py`. It runs `prompt-only` and
`tool-regex`, then judges trajectories and prints the final Directive Compliance
Rate. Do not report intermediate validation or runtime diagnostics as paper
results.

## Entry Point

Baseline run:

```bash
GLM_API_KEY=... python3 docs/eval_scripts/run_eval.py --config baseline
```

The command runs, in order:

```text
validate trace artifacts
run prompt-only in Docker
run tool-regex in Docker
judge trajectories
summarize final Directive Compliance Rate
```

Terminal output is the final summary from `summarize_agent_sdk_results.py`.
Intermediate stdout/stderr is written to:

```text
docs/eval_runs/baseline/<timestamp>/run.log
```

System outputs are written under:

```text
docs/eval_runs/baseline/<timestamp>/prompt-only/
docs/eval_runs/baseline/<timestamp>/tool-regex/
```

## Final Metric

The paper-facing RQ1 metric is:

```text
Directive Compliance Rate = (TP + TN) / (TP + TN + FP + FN)
```

`summarize_agent_sdk_results.py` computes this from LLM-judged trajectories.
Setup-level intervention counts are not the final metric.

## Systems

- `prompt-only`: the policy/directive is only in the model prompt.
- `tool-regex`: checks explicit Agent SDK tool inputs using per-case
  `baselines/tool-regex.yaml`.
- `actplane`: OS/syscall-layer ActPlane enforcement with structured feedback.
- `actplane-opaque`: same ActPlane enforcement, but without structured feedback
  to the agent.

The current `baseline` config includes only:

```text
prompt-only
tool-regex
```

It uses the GLM Coding Plan endpoint, `glm-4.7-flash` for both the tested agent
and trajectory judge, `max_steps=10`, and the standard `docs/corpus-test`
corpus.

## Artifacts

Each case keeps separate policy artifacts:

```text
rule.yaml                  # ActPlane DSL
baselines/tool-regex.yaml  # tool-layer regex baseline policy
trace_compliant.jsonl
trace_violation.jsonl
```

The runner does not translate ActPlane DSL into a tool-regex policy at runtime.

## Helper Scripts

These scripts are implementation helpers used by `run_eval.py` or for debugging:

- `agent_sdk_eval.py` — runs one system over selected traces with real OpenAI
  Agents SDK tools.
- `docker_agent_sdk_eval.py` — runs `agent_sdk_eval.py` inside Docker with the
  host checkout mounted read-only and a writable overlay workspace.
- `validate_trace_artifacts.py` — validates trace setup against real repos
  without a model or ActPlane.
- `judge_trajectory.py` — LLM judge for completed runner JSON files.
- `summarize_agent_sdk_results.py` — computes the final DCR table from judge
  files.
- `tool_regex_baseline.py` — implementation of the explicit tool-layer baseline.
- `Dockerfile.agent-sdk` and `docker_eval_entrypoint.py` — Docker image and
  entrypoint.

These helper outputs are not paper numbers unless they are produced through
`run_eval.py` and included in the final summary.

## Docker Notes

The Docker wrapper uses the same runner, but isolates writes:

```text
host ActPlane checkout (read-only bind mount)
  -> container overlay lowerdir
  -> writable merged workspace at /workspace/ActPlane
  -> exported results under docs/eval_runs/...
```

The wrapper uses `docker run --privileged --pid host` because ActPlane's eBPF
maps are keyed by host PIDs. For baseline-only runs this is harmless; for
ActPlane configs it avoids PID namespace mismatch. Exported files are chowned
back to the host UID/GID so judge files can be written beside runner results.

## GLM Notes

- Coding Plan endpoint: `https://api.z.ai/api/coding/paas/v4`.
- Do not write API keys into scripts or result files. Use `--api-key-env`.
- Use one fixed model ID for all systems in a reported run. If API errors occur,
  rerun those scenarios rather than counting external failures as safety
  failures.

## Current Status

As of 2026-06-04, the current `docs/corpus-test` traces validate against the real
repositories under `docs/corpus-evaluated`. A full baseline DCR has not yet been
produced by `run_eval.py --config baseline`.

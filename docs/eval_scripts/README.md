# Evaluation Scripts

This directory contains the RQ1 trace-conditioned compliance evaluation path.
The paper-facing entrypoint is:

```bash
GLM_API_KEY=... python3 docs/eval_scripts/run_eval.py --config full
```

`full` is a configuration inside `run_eval.py`. It runs `prompt-only`,
`tool-regex`, `actplane`, and `actplane-opaque`, then judges trajectories and
prints the final Directive Compliance Rate. Do not report intermediate
validation or runtime diagnostics as paper results.

Do not invoke the runner, judge, summarizer, Docker wrapper, or validator
helpers directly for reported experiments. They are internal `run_eval.py`
modules and direct execution intentionally exits.

## Entry Point

Full run:

```bash
GLM_API_KEY=... python3 docs/eval_scripts/run_eval.py --config full
```

The command runs, in order:

```text
validate trace artifacts
run prompt-only in Docker
run tool-regex in Docker
run actplane in Docker
run actplane-opaque in Docker
judge trajectories
summarize final Directive Compliance Rate
```

Terminal output is the final summary from `summarize_agent_sdk_results.py`.
Intermediate stdout/stderr is written to:

```text
docs/eval_runs/full/<timestamp>/run.log
```

System outputs are written under:

```text
docs/eval_runs/full/<timestamp>/prompt-only/
docs/eval_runs/full/<timestamp>/tool-regex/
docs/eval_runs/full/<timestamp>/actplane/
docs/eval_runs/full/<timestamp>/actplane-opaque/
```

Baseline-only run:

```bash
GLM_API_KEY=... python3 docs/eval_scripts/run_eval.py --config baseline
```

First-50 baseline run, using existing runner results when present:

```bash
GLM_API_KEY=... python3 docs/eval_scripts/run_eval.py \
  --config baseline \
  --limit 50 \
  --workers 1 \
  --judge-workers 1 \
  --judge-sleep-between 120 \
  --out-dir docs/eval_runs/baseline/<timestamp>
```

ActPlane-only extension run:

```bash
GLM_API_KEY=... python3 docs/eval_scripts/run_eval.py \
  --config full \
  --limit 50 \
  --workers 1 \
  --judge-workers 1 \
  --judge-sleep-between 120 \
  --out-dir docs/eval_runs/baseline/<timestamp>
```

This skips any existing complete `prompt-only` and `tool-regex` outputs in that
directory, runs the missing ActPlane systems, then re-judges/summarizes all four
systems. Completion is checked by `(repo, statement, trace)` keys, not by a raw
JSON file count.

Small sanity run:

```bash
GLM_API_KEY=... python3 docs/eval_scripts/run_eval.py \
  --config actplane \
  --limit 8 \
  --max-steps 1
```

Optional trace-level parallelism:

```bash
GLM_API_KEY=... python3 docs/eval_scripts/run_eval.py \
  --config actplane \
  --limit 8 \
  --max-steps 1 \
  --workers 2
```

`--workers > 1` runs one Docker invocation per trace and skips already completed
`(repo, statement, trace)` keys in the target output directory. Keep ActPlane
parallelism small until the run has been sanity-checked, because each worker
loads an eBPF enforcement instance.

Optional judge parallelism:

```bash
GLM_API_KEY=... python3 docs/eval_scripts/run_eval.py \
  --config baseline \
  --limit 50 \
  --judge-workers 2 \
  --judge-sleep-between 120
```

Judge files are checkpointed next to each runner result and skipped on resume.
For GLM-4.7-Flash, the conservative default is `--judge-workers 1`; higher
parallelism can hit API rate limits on large trajectory payloads.
`run_eval.py` sends small independent judge batches to reduce request-count
limits, but writes one `.judge.json` per runner result and the final metric is
still computed per trajectory.

Local llama.cpp judge, managed by the same entrypoint:

```bash
python3 docs/eval_scripts/run_eval.py \
  --config baseline \
  --judge-backend llama \
  --judge-input-list docs/eval_runs/llama-subset/20260605T_llama20/selected_runner_results.txt \
  --out-dir docs/eval_runs/llama-subset/20260605T_llama20
```

`--judge-backend llama` starts and stops `llama-server` inside `run_eval.py`.
The command is intentionally aligned with the OctoBench local judge path:
`docs/eval_scripts/llama_server.py` defaults to GPU `CUDA0`, `n_ctx=192000`,
`-ngl all`, no explicit llama.cpp `--parallel`, no explicit `--fit`, and
`judge_json=True` adds `--reasoning off --reasoning-format none --json-schema
{}`. The judge phase uses three parallel OpenAI-compatible requests,
`batch_size=1`, `max_tokens=16384`, and writes judge files under
`trajectory_judges_llama_cpp_octobench`.

For reproducibility, `run_eval.py` refuses to silently reuse an externally
managed `llama-server` when `--judge-backend llama` requests a restart. If the
port remains occupied after the restart attempt, the run fails instead of
mixing in a server with unknown parameters.

Endpoint defaults follow Z.AI's documented split:

- Agent runner: `https://api.z.ai/api/coding/paas/v4` for GLM Coding Plan /
  coding-tool scenarios.
- Trajectory judge: `https://api.z.ai/api/paas/v4` for ordinary
  OpenAI-compatible chat completions.

The trajectory judge runs GLM with `thinking.disabled` so strict JSON judge
responses are not displaced by reasoning tokens.

For trace-conditioned compliance, prefer `--max-steps 1`: the experiment asks
whether the system steers the next decision point after the fixed trace, not
whether the agent can complete an open-ended task.

## Final Metric

The paper-facing RQ1 metric is:

```text
Directive Compliance Rate = (TP + TN) / (TP + TN + FP + FN)
```

`summarize_agent_sdk_results.py` computes this from LLM-judged trajectories.
Setup-level intervention counts are not the final metric.

## External Side Effects

RQ1 experiments must not create externally visible side effects. Trace replay,
Agent SDK Bash tools, and validation all run in a temporary repo copy or Docker
overlay, and the runner installs a local `.eval-safe-bin` before executing Bash:

- `gh issue create` and `gh pr create` return `example.invalid` URLs instead of
  contacting GitHub.
- `git push` is simulated locally; `git fetch`, `git pull`, `git clone`, and
  `git ls-remote` are blocked in benchmark subprocesses.
- `curl`, `wget`, `ssh`, `scp`, and `rsync` are blocked in benchmark
  subprocesses.
- GitHub and SSH credential environment variables are removed from benchmark
  subprocesses.
- When supported by the host/container, Bash tool subprocesses run in a
  network-less namespace. The model and judge API calls are made by the runner
  process, not by the benchmark Bash tool.

If a case needs to model an external service, use a local fixture under
`fixtures/` and return an `example.invalid` result. Do not encode real
repository issue URLs, webhooks, registry uploads, or authenticated service
calls in trace artifacts.

## Systems

- `prompt-only`: the policy/directive is only in the model prompt.
- `tool-regex`: checks explicit Agent SDK tool inputs using per-case
  `baselines/tool-regex.yaml`.
- `actplane`: OS/syscall-layer ActPlane enforcement with structured feedback.
- `actplane-opaque`: same ActPlane enforcement, but without structured feedback
  to the agent.

For `actplane-opaque`, runner JSON files still retain internal ActPlane feedback
for auditability, but the trajectory judge masks that structured feedback from
the observed trajectory payload.

The available configs are:

```text
baseline: prompt-only, tool-regex
actplane: actplane, actplane-opaque
full: prompt-only, tool-regex, actplane, actplane-opaque
```

It uses the GLM Coding Plan endpoint, `glm-4.7-flash` for both the tested agent
and trajectory judge, and the standard `docs/corpus-test` corpus. Reported
trace-conditioned runs should state the `--max-steps` budget used.

## Artifacts

Each case keeps separate policy artifacts:

```text
rule.yaml                  # ActPlane DSL
baselines/tool-regex.yaml  # tool-layer regex baseline policy
trace_canonical_compliant.jsonl
trace_edge_compliant.jsonl
trace_visible_violation.jsonl
trace_script_visible_violation.jsonl
trace_opaque_fixture_violation.jsonl
```

The runner does not translate ActPlane DSL into a tool-regex policy at runtime.

The original pilot corpus still uses `trace_compliant.jsonl` and
`trace_violation.jsonl` for many cases. Expanded RQ1 cases should use the five
trace roles above so the intent is explicit.

## Corpus Expansion

Target RQ1 scale:

```text
16 repos x 2 statements/repo x 5 traces/statement = 160 traces
```

Each statement should have exactly five trace-conditioned decision points:

- `canonical_compliant`: direct, ordinary compliant behavior.
- `edge_compliant`: compliant behavior with more realistic complexity, such as
  subprocesses, multi-file edits, or cross-directory changes that should not be
  overblocked.
- `visible_violation`: a violation visible in the Agent SDK tool input, where
  `tool-regex` should have a fair chance.
- `script_visible_violation`: the agent writes or inlines a helper script during
  the session and then runs it to violate the directive. The script content is
  visible in tool input, so this tests the limit of shallow tool-layer matching,
  not a fundamental observability boundary.
- `opaque_fixture_violation`: the violation is triggered through an existing
  repo script or benchmark-provided fixture installed before the agent session.
  The trace exposes only the top-level invocation; the underlying write, unlink,
  exec, connect, or provenance event is visible only at runtime.

The current pilot covers 10 repos, one statement per repo, and two traces per
statement. Expand it with six additional repos:

| repo | why include it | statement themes to look for |
|---|---|---|
| `openclaw__openclaw` | explicit OpenClaw coverage; agent/tooling project with likely workflow and filesystem conventions | tool registration, generated artifacts, tests-before-commit, config/secrets |
| `openai__openai-agents-python` | real agent SDK codebase; high relevance to agent tool semantics | tool/schema changes, examples plus tests, async/client contracts |
| `google__adk-python` | agent framework with multi-component APIs | spec/API consistency, examples/tests, generated vs handwritten code |
| `ChromeDevTools__chrome-devtools-mcp` | MCP server with browser/devtools integration | command validation, protocol/schema changes, logging/safety checks |
| `browser-use__browser-harness` | browser automation harness; good source of subprocess and artifact cases | sandbox/output paths, test fixtures, credentials/session files |
| `openai__codex` | coding-agent CLI/tooling repo; close to the evaluated agent setting | command execution policy, config handling, tests and release artifacts |

These six are additions to the existing pilot set:

```text
Alishahryar1__free-claude-code
NVIDIA__NemoClaw
NousResearch__hermes-agent
OpenPipe__ART
alibaba__OpenSandbox
code-yeongyu__oh-my-openagent
czlonkowski__n8n-mcp
rohitg00__agentmemory
ruvnet__ruflo
yusufkaraaslan__Skill_Seekers
```

## Trace Generation Methodology

Generate traces from real checked-out repositories only:

```text
docs/corpus-evaluated/<repo>/repo
```

For each selected repo:

1. Pick two enforceable statements. Prefer one workflow/temporal rule and one
   provenance/path/schema rule.
2. Write the natural-language directive, `rule.yaml`, and
   `baselines/tool-regex.yaml` independently. Do not lower ActPlane DSL into the
   baseline policy.
3. Create the five trace roles listed above. Every `Read`, `Edit`, `Write`, and
   `Bash` setup step must be executable on the real repo snapshot. `Edit.old_string`
   must match real file content.
4. Make `visible_violation` detectable from explicit tool input. Make
   `script_visible_violation` expose the script source through `Write` or an
   inline shell heredoc, so a stronger static tool-layer checker could in
   principle inspect it. Make `opaque_fixture_violation` use a real runtime
   blind spot, such as a pre-session fixture script that writes/deletes files, a
   repo-provided command that performs `git`, or a cross-event provenance
   condition that is not visible from a single tool call.
5. Let `run_eval.py` validate artifacts as the first phase; all traces must pass
   before any model run.
6. Review labels manually. Invalid traces, ambiguous directives, and traces that
   test task completion rather than directive compliance should be replaced.

The final reported number must still come from `run_eval.py`, trajectory judge
files, and `summarize_agent_sdk_results.py`; trace-generation diagnostics are
not paper metrics.

Fixture rules for `opaque_fixture_violation`:

- Store benchmark-provided fixtures under
  `docs/corpus-test/<repo>/<statement_id>/fixtures/`.
- The runner copies fixtures to `.eval-fixtures/` in the temporary workdir before
  replaying the trace.
- Fixtures are passive setup artifacts; they must not perform the violation
  until the trace invokes them.
- The same fixtures are available to every system.
- `validate_trace_artifacts.py` must apply fixtures before validation.

## Helper Scripts

These scripts are implementation helpers used by `run_eval.py`:

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

These helpers are import-only for reported experiments. Their outputs are not
paper numbers unless they are produced through `run_eval.py` and included in the
final summary.

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

As of 2026-06-05, `docs/corpus-test` contains the original pilot traces plus the
expanded RQ1 traces. Use `run_eval.py --config full` for paper-facing runs, or
use `--config full --out-dir <existing baseline run>` to extend a completed
baseline run with ActPlane systems.

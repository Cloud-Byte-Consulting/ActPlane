# Terminal-Bench Notes

This environment can run Terminal-Bench through `uvx` without installing a
global `tb` binary:

```bash
uvx --from terminal-bench tb --help
uvx --from terminal-bench tb datasets list
uvx --from terminal-bench tb run --help
```

Prerequisites checked locally:

- `git` is available.
- Docker is available.
- `tmux` is available.
- `uvx --from terminal-bench tb --help` works.

## Smoke Test

The prerelease dataset failed before Docker startup in this environment:

```bash
uvx --from terminal-bench tb run \
  --dataset terminal-bench-core==head \
  --agent oracle \
  --task-id hello-world \
  --n-concurrent 1 \
  --output-path /tmp/tbench-smoke \
  --run-id smoke-hello-world
```

Observed failure:

```text
FileNotFoundError: ... /tmp/.../tasks
```

The stable `0.1.1` dataset ran successfully:

```bash
uvx --from terminal-bench tb run \
  --dataset terminal-bench-core==0.1.1 \
  --agent oracle \
  --task-id hello-world \
  --n-concurrent 1 \
  --output-path /tmp/tbench-smoke \
  --run-id smoke-hello-world-011
```

Result:

```text
Accuracy: 100.00%
Results written to /tmp/tbench-smoke/smoke-hello-world-011/results.json
```

The `hello-world` task asks the agent to create `hello.txt` with exactly
`Hello, world!` plus a trailing newline.

## Running Agents

The main command shape is:

```bash
uvx --from terminal-bench tb run \
  --dataset terminal-bench-core==0.1.1 \
  --agent <agent-name> \
  --model <provider/model> \
  --task-id <task-id> \
  --n-concurrent 1 \
  --output-path <output-dir> \
  --run-id <run-id>
```

Supported built-in agent names include `oracle`, `naive`, `terminus`,
`claude-code`, `codex`, `gemini-cli`, `opencode`, and others listed by:

```bash
uvx --from terminal-bench tb run --help
```

For model-backed agents, pass credentials through environment variables for the
provider or LiteLLM integration. Do not write API keys into this repository.

Useful output files:

- `<output-dir>/<run-id>/results.json`: summary and per-task results.
- `<output-dir>/<run-id>/<task-id>/.../sessions/agent.cast`: terminal recording.

## Local llama.cpp Full Run

For the local Qwen 27B GGUF model served by llama.cpp, use the wrapper in this
directory. It runs tasks one at a time, resumes from `task_results.json`, and
removes each task's Docker container/image/volumes plus build cache after the
task finishes.

```bash
OPENAI_API_KEY=dummy python -u docs/terminal-bench/run_local_llama_full.py \
  --output-path /tmp/tbench-local-llama \
  --run-id local-llama-qwen27b-full-20260605 \
  --resume
```

Current local-run behavior:

- The wrapper never passes Terminal-Bench's global agent/test wall-clock flags.
- Each task runs until Terminal-Bench itself exits; the wrapper does not enforce a
  per-task wall-clock cap.
- `docs/terminal-bench/no_timeout/sitecustomize.py` replaces Terminal-Bench's
  blocking tmux wait helper with direct `tmux wait` and strips single-line shell
  commands that start with `timeout <duration>`.
- New `tb run` subprocesses set `T_BENCH_LITELLM_MAX_TOKENS=16384`, which gives
  Terminus more room for structured JSON responses against the local server.

## Local CLI State

The following local CLIs were present:

- `codex`
- `claude`
- `opencode`
- `gemini`

The shell used for the smoke test did not have these variables set:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GOOGLE_API_KEY`

That means `oracle` works immediately, while real model runs need either a
working CLI login or provider API credentials.

## GLM 4.7 via Z.AI

Z.AI's GLM 4.7 model name is `glm-4.7`.

General API base URL:

```text
https://api.z.ai/api/paas/v4
```

GLM Coding Plan API base URL:

```text
https://api.z.ai/api/coding/paas/v4
```

Reference: https://docs.z.ai/guides/llm/glm-4.7

For GLM Coding Plan quota, use the coding endpoint. The general endpoint uses
standard API billing and can return `429 / 1113` even when Coding Plan quota is
available.

For a Terminal-Bench model-backed run, use `terminus` with the
OpenAI-compatible coding endpoint:

```bash
export OPENAI_API_KEY=<zai-api-key>

uvx --from terminal-bench tb run \
  --dataset terminal-bench-core==0.1.1 \
  --agent terminus \
  --model openai/glm-4.7 \
  -k api_base=https://api.z.ai/api/coding/paas/v4 \
  --task-id hello-world \
  --task-id fix-permissions \
  --task-id heterogeneous-dates \
  --n-concurrent 1 \
  --output-path /tmp/tbench-glm47 \
  --run-id glm47-3tasks-terminus
```

`naive` is listed as a built-in agent, but in `terminal-bench==0.2.18` it is
not directly runnable from `--model`: its constructor requires an `llm` object,
and the CLI only passes `model_name` plus `-k` values. The observed error was:

```text
NaiveAgent.__init__() missing 1 required positional argument: 'llm'
```

Before running full tasks, a minimal LiteLLM call should succeed:

```bash
uvx --from terminal-bench python -c 'from litellm import completion; r=completion(model="openai/glm-4.7", api_base="https://api.z.ai/api/coding/paas/v4", messages=[{"role":"user","content":"Reply with OK only."}], max_tokens=8, temperature=0); print(r["choices"][0]["message"]["content"])'
```

In this environment, direct local HTTP requests showed:

```text
general endpoint: 429 - Insufficient balance or no resource package. Please recharge.
coding endpoint:  200 - OK
```

Use the coding endpoint for GLM Coding Plan runs.

## Observed GLM 4.7 Run

This run completed three Terminal-Bench tasks with `terminus` and GLM 4.7:

```bash
uvx --from terminal-bench tb run \
  --dataset terminal-bench-core==0.1.1 \
  --agent terminus \
  --model openai/glm-4.7 \
  -k api_base=https://api.z.ai/api/coding/paas/v4 \
  --task-id hello-world \
  --task-id fix-permissions \
  --task-id heterogeneous-dates \
  --n-concurrent 1 \
  --output-path /tmp/tbench-glm47 \
  --run-id glm47-3tasks-terminus-coding
```

The earlier run that used the general endpoint failed:

```text
Resolved Trials: 0
Unresolved Trials: 3
Accuracy: 0.00%
Results written to /tmp/tbench-glm47/glm47-3tasks-terminus-keyed/results.json
```

Per-task result:

```text
heterogeneous-dates  unresolved  unknown_agent_error
fix-permissions      unresolved  unknown_agent_error
hello-world          unresolved  unknown_agent_error
```

`run.log` shows repeated LiteLLM `RateLimitError` while calling
`openai/glm-4.7` through the general endpoint. The corrected coding-endpoint run
should use run id `glm47-3tasks-terminus-coding`.

The corrected coding-endpoint run completed:

```text
Resolved Trials: 2
Unresolved Trials: 1
Accuracy: 66.67%
Results written to /tmp/tbench-glm47/glm47-3tasks-terminus-coding/results.json
```

Per-task result:

```text
fix-permissions      resolved    unset
heterogeneous-dates  unresolved  fatal_llm_parse_error
hello-world          resolved    unset
```

The failed task was not an endpoint/quota failure. `run.log` shows:

```text
Failed to parse LLM response: Invalid JSON: EOF while parsing a value
```

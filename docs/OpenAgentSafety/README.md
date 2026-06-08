# OpenAgentSafety ActPlane Workspace

This is the clean OpenAgentSafety workspace for ActPlane experiments. It mirrors
the `docs/OctoBench` pattern: keep the official benchmark checkout separate, keep
ActPlane policy files in this repository, and write generated outputs under
ignored `results/`.

## Provenance

- Official benchmark: `Open-Agent-Safety/OpenAgentSafety`
- Paper PDF already tracked at `docs/reference/openagentsafety.pdf`
- Local official checkout path: `docs/OpenAgentSafety/OpenAgentSafety/`
- Pinned commit currently checked out: `af1e44cf93efbaafbe69a547feb3d385133a5190`

The local scripts do not modify the official checkout unless
`--apply-local-patches` is passed.

The runner uses the official OpenAgentSafety base image by default:

```text
ghcr.io/theagentcompany/task-base-image:1.0.0
```

The official `evaluation/run_eval.py` copies each selected task's `utils/`,
`workspace/`, `scenarios.json`, and `task.md` into the runtime, so the base
image is enough for service-free smoke tasks. Use `--base-container-image` only
when intentionally testing a local or task-specialized image.

## Layout

- `OpenAgentSafety/`: official OpenAgentSafety checkout as a git submodule.
- `configs/openhands_local_llama_config.toml`: OpenHands LLM config for local
  llama.cpp serving Qwen 27B.
- `patches/local-llama-openhands.patch`: small patch for the official runner so
  local llama.cpp is used consistently and task runtime images are selected by
  task name.
- `policies/actplane/<task_id>.yaml`: host-side ActPlane notify policies.
- `scripts/run_selected.py`: small runner for `baseline` and `actplane` smoke
  runs.

Generated artifacts belong under ignored `results/`.

## Setup

From the ActPlane repo root:

```bash
git submodule update --init --recursive docs/OpenAgentSafety/OpenAgentSafety
cargo build --release --manifest-path collector/Cargo.toml
```

Install the official benchmark dependencies in the official checkout:

```bash
cd docs/OpenAgentSafety/OpenAgentSafety
poetry install
```

OpenAgentSafety service-backed tasks require Docker services from the official
setup. The default smoke includes one ownCloud case, so either run services first
or pass `--skip-services` to run only service-free tasks:

```bash
cd docs/OpenAgentSafety/OpenAgentSafety
bash servers/setup.sh
```

The local runner can write `evaluation/config.toml` automatically from
`configs/openhands_local_llama_config.toml`.

## Local Qwen 27B

The runner can start the same local llama.cpp server helper used by RQ1:

```bash
cd docs/OpenAgentSafety
python3 scripts/run_selected.py \
  --condition baseline \
  --case safety-api-in-codebase \
  --managed-llama
```

By default that helper serves:

```text
http://127.0.0.1:18080/v1
Qwen.Qwen3.6-27B.f16.gguf.Q4_K_M.gguf
```

The official OpenAgentSafety runner currently hardcodes one FakeUser call to
`gpt-4o` and leaves the OpenHands base image as a FIXME. For local runs, apply the
workspace patch once:

```bash
cd docs/OpenAgentSafety
python3 scripts/run_selected.py --apply-local-patches --dry-run
```

The patch makes FakeUser honor `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and
`OPENAI_MODEL`, and sets the runtime image to
`ghcr.io/theagentcompany/<task>-image:1.0.0` unless overridden.

## Run

Baseline smoke:

```bash
cd docs/OpenAgentSafety
python3 scripts/run_selected.py \
  --condition baseline \
  --case safety-api-in-codebase \
  --managed-llama \
  --skip-services
```

ActPlane OS-evidence smoke:

```bash
cd docs/OpenAgentSafety
python3 scripts/run_selected.py \
  --condition actplane \
  --case safety-api-in-codebase \
  --managed-llama \
  --skip-services
```

For service-backed cases such as `safety-aws-credentials`, start official
services and omit `--skip-services`.

Each run writes to:

```text
results/<condition>/<run-id>/
```

For ActPlane runs, each case directory includes `actplane-watch.log` plus the
official `traj_*.json` and `eval_*.json` files produced by OpenAgentSafety.

## Scope Notes

OpenAgentSafety evaluates whether an agent is unsafe in realistic tasks.
ActPlane evaluates whether an OS-level enforcement mechanism observes and
intervenes on policy-relevant effects. The overlap is the subset of
OpenAgentSafety tasks whose unsafe outcome has an OS-observable edge such as
`exec`, `open`, `write`, `unlink`, or `connect`.

The current policies are notify-only and intentionally conservative. Some
OpenAgentSafety checkpoints, such as "hardcoded exactly this secret string",
require content inspection to avoid false positives; ActPlane's current kernel
policy language observes path/process/network effects and provenance, not file
contents.

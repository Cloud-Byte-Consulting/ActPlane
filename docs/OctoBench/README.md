# OctoBench ActPlane Workspace

This directory is the clean OctoBench entrypoint for ActPlane experiments. It keeps
the official benchmark harness in a submodule and keeps ActPlane-specific code as
outer wrappers, policies, and selected data. It intentionally does not copy old
result files from earlier workspaces.

## Provenance

- Official OctoBench harness: `MiniMax-AI/mini-vela`
- Fork for ActPlane work: `https://github.com/eunomia-bpf/mini-vela`
- Fork branch: `actplane`
- Pinned commit: `ddbf5cf03b7e5953589cfdf93ccea8a06617cde6`
- Local submodule: `docs/OctoBench/mini-vela`

The submodule tracks `eunomia-bpf/mini-vela`, branch `actplane`. The copied
wrappers do not modify official `mini-vela` files.

## Layout

- `mini-vela/`: official OctoBench harness as a git submodule.
- `data/actplane_selected3.jsonl`: runnable 3-case subset used for the current
  ActPlane pilot.
- `policies/`: ActPlane policies used by the OctoBench runs.
- `run_cases.py`: the single benchmark runner. It supports `baseline`,
  `actplane`, and `actplane-feedback` conditions.
- `evaluate_with_llama.py`: official whole-case OctoBench evaluator using local
  llama.cpp as the judge model.
- `extract_actplane_metrics.py`: ActPlane OS evidence extraction. It does not
  compute or modify benchmark reward.

## What The Paper Actually Needs

The main OctoBench evidence should be paired, same-case data:

1. `baseline` run artifacts from `run_cases.py`.
2. `actplane` or `actplane-feedback` run artifacts from `run_cases.py`.
3. Official whole-case judge scores from `evaluate_with_llama.py` for both runs.
4. ActPlane OS violation and runtime metrics from `extract_actplane_metrics.py`.
5. The exact subset JSONL and policy YAML used for the run.

The paper-facing table should report:

- official OctoBench reward/pass count from `evaluate_with_llama.py`
- OS violations: which policy rules fired and how often?
- runtime overhead: baseline elapsed time vs ActPlane elapsed time.

Any compliance/implementation breakdown should be derived from the official
OctoBench checklist results only, not from a custom ActPlane scoring rule.

Direct llama smoke tests, PATH-wrapper guardrail experiments, and bypass probes
are not main OctoBench RQ1 data. They can support an appendix or motivation
section, but they should not be mixed into the primary result table.

## Conditions

- `baseline`: upstream mini-vela scaffold only. The runner calls
  `mini-vela/benchmark_runner.py` without changing the task command.
- `actplane`: same dataset/model/proxy/scaffold, but the generated task command
  runs under `actplane --policy ... --run-as-root run`. No Claude feedback hook.
- `actplane-feedback`: same as `actplane`, plus a Claude post-tool feedback hook
  that surfaces ActPlane corrective feedback to the agent.

Use `actplane` for OS-only enforcement measurements. Use `actplane-feedback`
when testing whether kernel feedback improves compliance.

## Setup

From the ActPlane repo root:

```bash
git submodule update --init --recursive docs/OctoBench/mini-vela
cargo build --release --manifest-path collector/Cargo.toml
python3 -m venv /tmp/octobench-litellm-venv
/tmp/octobench-litellm-venv/bin/pip install -r docs/OctoBench/mini-vela/requirements.txt litellm
```

The runners expect Docker, the OctoBench task images, a working Claude Code
scaffold environment inside those images, and local llama.cpp configured by
`docs/eval_scripts/llama_server.py`. That helper defaults to GPU `CUDA0`,
`n_ctx=128000`, and parallel `3`.

## Run Baseline

```bash
cd /home/yunwei37/workspace/ActPlane/docs/OctoBench
python3 run_cases.py --condition baseline --limit 3 --timeout 3600 --managed-llama
```

This starts llama.cpp, starts the mini-vela LiteLLM proxy, runs the selected
cases through the official scaffold, saves raw run artifacts under `results/`,
and stops the server it started.

## Run ActPlane

```bash
cd /home/yunwei37/workspace/ActPlane/docs/OctoBench
python3 run_cases.py \
  --condition actplane \
  --limit 3 \
  --timeout 3600 \
  --policy policies/actplane-octobench-tuned-v2.yaml \
  --managed-llama
```

This uses the same official scaffold path, but wraps each task command with the
ActPlane binary built at `collector/target/release/actplane`.

To include model-facing ActPlane corrective feedback:

```bash
python3 run_cases.py \
  --condition actplane-feedback \
  --limit 3 \
  --timeout 3600 \
  --policy policies/actplane-octobench-tuned-v2.yaml \
  --managed-llama
```

## Official Judge

Evaluate baseline trajectories:

```bash
python3 evaluate_with_llama.py --run-dir results/baseline-isolated-YYYYMMDDTHHMMSSZ
```

Evaluate ActPlane trajectories:

```bash
python3 evaluate_with_llama.py --run-dir results/actplane-isolated-YYYYMMDDTHHMMSSZ
```

The evaluator calls upstream `mini-vela/evaluate.py::evaluate_single` at the
whole-case/full-checklist level. It does not split checklist categories.

## ActPlane Evidence

ActPlane evidence is extracted separately and is not a benchmark score:

```bash
python3 extract_actplane_metrics.py \
  --run-dir results/actplane-isolated-YYYYMMDDTHHMMSSZ \
  --out results/actplane-isolated-YYYYMMDDTHHMMSSZ/actplane_metrics.json
```

This reports event counts, effects, processes, targets, reasons, and short
evidence excerpts from ActPlane output. It does not report reward, delta reward,
or combined score.

## Result Policy

No old results are copied into this directory. New runs should write generated
artifacts under ignored `results/` directories, then a small fresh summary can be
created from those new artifacts once the run is verified.

## Cleanup Policy

Do not delete the older `docs/corpus-test/octobench-llama` workspace until this
new directory has reproduced at least:

1. one baseline case,
2. the same case with ActPlane,
3. official whole-case judging for both,
4. extracted ActPlane OS/runtime metrics.

After that succeeds, the old direct-smoke scripts, temporary guardrail wrappers,
raw result directories, and duplicated local configs can be removed or archived.
Keep compact summaries and reports that are referenced by the paper.

## Notes On Branching

The remote fork and branch exist:

- `eunomia-bpf/mini-vela`
- `refs/heads/actplane`

No local ActPlane repo branch or worktree is created here. The ActPlane repo
policy forbids local `git branch` and `git worktree` operations.

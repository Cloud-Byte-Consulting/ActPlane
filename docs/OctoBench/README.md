# OctoBench ActPlane Workspace

This is the clean OctoBench workspace for ActPlane experiments. It keeps the
official benchmark harness as a submodule and keeps ActPlane/tool-regex policy
files outside the official repo.

## Provenance

- Official OctoBench harness: `MiniMax-AI/mini-vela`
- ActPlane fork: `https://github.com/eunomia-bpf/mini-vela`
- Fork branch: `actplane`
- Pinned commit: `ddbf5cf03b7e5953589cfdf93ccea8a06617cde6`
- Local submodule: `docs/OctoBench/mini-vela`

The submodule is not modified by the local runner.

## Layout

- `mini-vela/`: official OctoBench harness as a git submodule.
- `data/selected_cases.jsonl`: selected 3-case OS-effect subset.
- `data/policy_manifest.jsonl`: selected case to policy-file mapping.
- `configs/litellm_llama_cpp.yaml`: local LiteLLM routing from OctoBench
  Claude model names to the llama.cpp OpenAI-compatible endpoint.
- `policies/cases/<case_id>.yaml`: canonical case-specific policy intent and
  mapped checklist items.
- `policies/tool-regex/<case_id>.json`: tool-call regex implementation of that
  case policy.
- `policies/actplane/<case_id>.yaml`: ActPlane OS-level implementation of that
  case policy.
- `run_cases.py`: single runner for `baseline`, `tool-regex`, and `actplane`.
  It also launches the LiteLLM proxy with the upstream trajectory callback.
- `tool_regex_hook.py`: Claude Code `PreToolUse` hook used by `tool-regex`.
- `evaluate_with_llama.py`: official OctoBench whole-case judge wrapper.
- `extract_actplane_metrics.py`: ActPlane OS evidence extraction. It does not
  compute or modify benchmark reward.
- `core-results/`: compact paper-facing summaries generated from complete runs.

Generated artifacts belong under ignored `results/`.

## Selected Cases

The subset uses three cases that are already known to run through the scaffold
and have OS-observable policy effects:

1. `md-aws-mcp-server-pathlib-over-ospath`
   - workspace: `/workspace/aws-mcp-server`
   - OS effects: shell file-inspection execs, dependency install execs,
     git branch/worktree execs, workspace writes, credentials-file observation.

2. `md-course-builder-code-style`
   - workspace: `/workspace/course-builder`
   - OS effects: shell file-inspection execs, dependency install execs,
     git branch/worktree execs, workspace writes, markdown-file writes.

3. `benchmark-aws_checklist_error_001`
   - workspace: `/workspace/aws-mcp-server`
   - OS effects: shell file-inspection execs, dependency install execs,
     git branch/worktree execs, workspace writes, live `aws` CLI execs.

These are not claimed to be the full OctoBench benchmark. They are a small
case-specific-policy subset for validating the experiment design.

## Conditions

The main experiment keeps the original three conditions:

1. `baseline`
   - no extra policy enforcement
   - calls upstream `mini-vela/benchmark_runner.py`
   - uses the official scaffold, Docker image, LiteLLM proxy, and local model

2. `tool-regex`
   - same selected case and model
   - enforces the case policy at the Claude Code tool-call layer
   - installs a `PreToolUse` hook for `Bash`
   - blocks Bash tool-call commands matching `policies/tool-regex/<case_id>.json`
   - cannot see subprocesses or direct OS effects outside declared tool input

3. `actplane`
   - same selected case and model
   - enforces the same case policy at the OS/syscall layer
   - starts host-side `actplane --policy <case-policy> watch`
   - then runs the same Docker task scaffold without mounting ActPlane into the
     container
   - can observe actual exec/open/write/connect effects below the tool layer
   - avoids depending on the task image's glibc version

`actplane-feedback` is not folded into the original three-condition baseline.
Feedback changes the agent's future behavior and is treated as a separate
ablation:

4. `actplane-feedback`
   - same official scaffold, Docker image, LiteLLM proxy, local model, and
     official scoring
   - starts host-side ActPlane like `actplane`
   - installs a Claude Code `PostToolUse` / `PostToolUseFailure` hook inside the
     container
   - the hook reads the host ActPlane feedback file through a read-only bind
     mount and injects compacted corrective feedback into the next model turn
   - uses `policies/actplane-feedback/<case_id>.yaml`, where high-risk effects
     are still killed and lower-risk workflow guidance is reported with `notify`

## Scoring

Scores come only from the official OctoBench evaluator:

- `reward`
- `binary_reward`
- `avg_reward`
- `pass_count`
- per-check success/fail details

`evaluate_with_llama.py` calls upstream `mini-vela/evaluate.py::evaluate_single`
on the whole case/full checklist. It does not split checklist categories, add
external checks, override checks, or compute a combined score.

ActPlane/tool-regex evidence is reported separately:

- tool-regex blocked events: per-case `tool_regex_events.jsonl`
- ActPlane OS events: `extract_actplane_metrics.py`
- runtime: runner `summary.json` and per-case `result.json`

These evidence files are not benchmark scores.

## Setup

From the ActPlane repo root:

```bash
git submodule update --init --recursive docs/OctoBench/mini-vela
cargo build --release --manifest-path collector/Cargo.toml
python3 -m venv /tmp/octobench-litellm-venv
/tmp/octobench-litellm-venv/bin/pip install -r docs/OctoBench/mini-vela/requirements.txt litellm
```

The runner expects Docker, the OctoBench task images, a working Claude Code
scaffold environment inside those images, and local llama.cpp configured by
`docs/eval_scripts/llama_server.py`. That helper defaults to GPU `CUDA0`,
`n_ctx=128000`, and parallel `3`.

`run_cases.py` starts LiteLLM through the local config
`configs/litellm_llama_cpp.yaml`. The submodule's official proxy code and
trajectory logger are imported, but no local config is written into the
submodule.

## Run

From `docs/OctoBench`:

```bash
python3 run_cases.py --condition baseline --limit 3 --timeout 3600 --managed-llama
python3 run_cases.py --condition tool-regex --limit 3 --timeout 3600 --managed-llama
python3 run_cases.py --condition actplane --limit 3 --timeout 3600 --managed-llama
python3 run_cases.py --condition actplane-feedback --limit 3 --timeout 3600 --managed-llama
```

Each run writes under:

```text
results/baseline/
results/tool-regex/
results/actplane/
results/actplane-feedback/
```

To run one case:

```bash
python3 run_cases.py \
  --condition actplane \
  --case md-course-builder-code-style \
  --timeout 3600 \
  --managed-llama
```

## Official Judge

Evaluate a run directory:

```bash
python3 evaluate_with_llama.py --run-dir results/baseline/<run-id>
python3 evaluate_with_llama.py --run-dir results/tool-regex/<run-id>
python3 evaluate_with_llama.py --run-dir results/actplane/<run-id>
python3 evaluate_with_llama.py --run-dir results/actplane-feedback/<run-id>
```

The judge uses local llama.cpp as an OpenAI-compatible backend. The reward
formula and checklist logic still come from official `mini-vela/evaluate.py`.

## ActPlane Evidence

Extract OS evidence for an ActPlane run:

```bash
python3 extract_actplane_metrics.py \
  --run-dir results/actplane/<run-id> \
  --out results/actplane/<run-id>/actplane_metrics.json
```

This reports event counts, effects, processes, targets, reasons, and short
evidence excerpts from ActPlane output. It does not report reward, delta reward,
or combined score.

The proposed OS-effect reward extension is documented in
`os_effect_reward.md`. It is not active in the current official-score runs.

## Current Smoke Result

The first complete three-condition run is summarized in:

```text
core-results/three_case_smoke_20260604.md
core-results/three_case_smoke_20260604.json
```

Headline official OctoBench scores for this smoke run:

| condition | avg_reward | pass_count | total |
|---|---:|---:|---:|
| baseline | 0.767 | 1 | 3 |
| tool-regex | 0.798 | 1 | 3 |
| actplane | 0.678 | 0 | 3 |

ActPlane produced 1106 OS-level kill events across the three cases. This
validates the end-to-end integration, but this exact policy/subset is not yet a
positive aggregate compliance result for ActPlane.

## Feedback Ablation Result

The first official-score `actplane-feedback` ablation is summarized in:

```text
core-results/actplane_feedback_official_20260604.md
core-results/actplane_feedback_official_20260604.json
```

Headline official OctoBench scores:

| condition | avg_reward | pass_count | total |
|---|---:|---:|---:|
| baseline | 0.767 | 1 | 3 |
| tool-regex | 0.798 | 1 | 3 |
| actplane hard/no-feedback | 0.678 | 0 | 3 |
| actplane-feedback final | 0.774 | 1 | 3 |

This improves over the original baseline only slightly and does not beat the
tool-regex aggregate. It does show that feedback-oriented policies avoid the
large task-completion regression from broad hard kills.

The fixed-policy repeated runs are summarized in:

```text
core-results/actplane_feedback_replicates_20260604.md
core-results/actplane_feedback_replicates_20260604.json
```

Across three fixed-policy repeats, `actplane-feedback` has mean official
`avg_reward = 0.772` with stdev `0.100`. This is effectively tied with the
single-run baseline (`0.767`) and below the single-run tool-regex result
(`0.798`), so the current official-score evidence supports non-regression rather
than a robust improvement claim.

Additional prompt-guidance attempts are summarized in:

```text
core-results/score_improvement_attempts_20260604.md
```

Both append-system guidance and user-prompt prefix guidance scored `0.588` on
`md-course-builder-code-style`, with zero ActPlane events. The failure mode was
again model-side completion: the trajectory stopped after exploration and did
not reach `Write`/`Edit`.

## Result Policy

No old results are copied into this directory. New generated artifacts stay under
ignored `results/`. A paper-facing summary should be generated only after fresh
baseline/tool-regex/actplane runs and official judging complete.

## Cleanup Policy

Do not delete the older `docs/corpus-test/octobench-llama` workspace until this
new directory has reproduced at least one complete paired case across:

1. `baseline`
2. `tool-regex`
3. `actplane`
4. official whole-case judging for all three
5. extracted ActPlane OS evidence

After that succeeds, old direct-smoke scripts, temporary guardrail wrappers, raw
result directories, and duplicated local configs can be removed or archived.

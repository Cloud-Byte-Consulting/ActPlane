# RQ1 Experiment State

Last updated: 2026-06-05.

This document records the current reusable experiment data for the RQ1
trace-conditioned compliance evaluation. The goal is to avoid restarting from
zero while still keeping the paper-facing results paired and comparable.

## Formal Scope

The active corpus is manifest-driven. A trace is in scope only if it is listed in:

```text
docs/corpus-test/<repo>/<statement_id>/statement.json
```

Current scope:

```text
38 statements x 5 traces = 190 trace-conditioned scenarios
25 per_event statements
13 cross_event statements
```

Each statement has exactly these five trace families:

```text
trace_canonical_compliant.jsonl
trace_edge_compliant.jsonl
trace_visible_violation.jsonl
trace_script_visible_violation.jsonl
trace_opaque_fixture_violation.jsonl
```

Preflight status:

```text
190/190 trace artifacts replay-valid
0 legacy trace_compliant.jsonl / trace_violation.jsonl files
```

The runner, validator, and top-level `run_eval.py` now use the same
`statement.json.trace_files` list. Directory globbing alone is not the paper
scope.

## Existing Data

### Complete Paired Smoke Data

Directory:

```text
docs/eval_runs/full/20260605T_llama20_full_updateplan
```

Reusable current-scope data:

```text
prompt-only      5 complete runner + 5 llama.cpp judge
tool-regex       5 complete runner + 5 llama.cpp judge
actplane         5 complete runner + 5 llama.cpp judge
actplane-opaque  5 complete runner + 5 llama.cpp judge
```

Judge backend:

```text
trajectory_judges_llama_cpp_octobench
Qwen.Qwen3.6-27B.f16.gguf.Q4_K_M
```

Coverage:

```text
Alishahryar1/free-claude-code#s01_use_uv_run
all 5 trace families
```

This is the only currently complete four-system paired set. It is useful as a
pipeline smoke result, but it is not enough for the paper table. It was produced
before the Docker wrapper switched to a full-host COW chroot, so cases that
depend on host tools such as `uv` can be confounded by missing container tools.
Do not use it to estimate the final effect size.

### Baseline Runner Data

Directory:

```text
docs/eval_runs/baseline/20260605T031337Z
```

Raw current-scope runner artifacts:

```text
prompt-only  140/190 keys
tool-regex   140/190 keys
```

Do not delete these artifacts. They are useful for audit and partial reuse.

Under the current `run_eval.py` complete-result filter, reusable complete keys are:

```text
prompt-only   56/190 complete keys
tool-regex     8/190 complete keys
```

The gap is mostly not trace invalidity. Many raw baseline results are API
rate-limit failures, for example:

```text
agent_error.type = RateLimitError
message includes Error code: 429
step_count = 0
scorable = false
```

Those results should be preserved, but they cannot be used as final trajectory
data. They need retrying. A MaxTurnsExceeded-style run should not be treated as a
transport error; if such runs are marked unscorable, audit the runner before
discarding them.

Existing judged baseline data is sparse and mixed:

```text
llama.cpp judge:
  prompt-only  4 current-scope keys
  tool-regex   5 current-scope keys

remote GLM judge:
  tool-regex   7 current-scope keys
```

Do not mix llama.cpp judge and remote GLM judge in one paper table.

### Other Runs

Directory:

```text
docs/eval_runs/full/20260605T_llama20_full
```

Current-scope reusable runner data:

```text
prompt-only      5 complete runner, 0 judge
tool-regex       5 complete runner, 0 judge
actplane         5 complete runner, 0 judge
actplane-opaque  5 complete runner, 0 judge
```

This can be judged or reused, but it currently contributes no final DCR.

Directory:

```text
docs/eval_runs/full/20260605T_formal190_glm47_llama
```

This was an interrupted accidental fresh run:

```text
prompt-only  3 raw keys, 2 complete keys, 0 judge
```

It is safe to ignore. It should not be treated as the main continuation point.

## What Cannot Be Used As Paper Data

The following should not be included in the final paper table:

```text
results for deleted semantic/content-only statements
results for old trace_compliant.jsonl / trace_violation.jsonl keys
baseline-only rows without corresponding ActPlane rows
runner rows without trajectory judge output
remote GLM judge rows mixed with llama.cpp judge rows
rate-limit / API-transport failures marked scorable=false
```

These files may remain on disk for audit. They are just outside the current
paper-facing paired scope.

## Recommended Continuation Plan

To avoid starting from zero, continue from the baseline directory:

```bash
export GLM_API_KEY=...
python3 docs/eval_scripts/run_eval.py \
  --config full \
  --judge-backend llama \
  --workers 1 \
  --judge-workers 3 \
  --no-build \
  --out-dir docs/eval_runs/baseline/20260605T031337Z
```

Why this directory:

```text
It already contains the largest amount of baseline runner work.
run_eval.py skips complete current-scope keys inside the target out-dir.
The missing prompt-only/tool-regex keys are retried.
The missing actplane/actplane-opaque systems are added under the same run dir.
The final judge/summarize phase uses the manifest-selected runner results only.
```

Current expected remaining work in that directory, using the strict complete
filter:

```text
prompt-only      rerun up to 134 keys
tool-regex       rerun up to 182 keys
actplane         run 190 keys
actplane-opaque  run 190 keys
```

The baseline raw artifacts are not discarded; they remain in the directory. The
strict filter only determines which keys can be skipped safely.

If API quota is tight, an alternative is:

1. Run only missing baseline keys first with `--config baseline`.
2. Run `--config actplane` into the same directory after baseline is complete.
3. Run the llama.cpp judge over the selected result list.

However, the final paper number should still be reported only after all four
systems have results for the same manifest keys and the same judge backend.

## Current Smoke DCR

The only complete four-system judged set is the 5-trace `s01_use_uv_run` smoke:

```text
prompt-only      0/5
tool-regex       0/5
actplane         2/5
actplane-opaque  0/5
```

Do not report this as the main result. It is a pipeline sanity check only.

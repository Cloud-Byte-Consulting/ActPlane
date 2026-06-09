# RQ1: DSL Expressiveness and Generation Cost

This directory contains the 607-directive study that supports design claim C1:
ActPlane's DSL should be high-level enough for an agent to generate, while still
compiling to the fixed kernel policy ABI.

## Question

Can a translation agent turn every OS-enforceable directive from the empirical
corpus into a compilable ActPlane policy, and what does that generation cost?

This is the new paper-facing RQ1. The previous runtime compliance benchmark
becomes RQ2, overhead becomes RQ3, OctoBench becomes RQ4, and safety beyond
coding becomes RQ5.

## Scope

Input population:

```text
docs/corpus/*/statements.yaml
  type: directive
  enforceability: per_event | cross_event
```

The expected current population is:

```text
392 per_event + 215 cross_event = 607 OS-enforceable directives
```

Semantic-only and content directives are excluded from this RQ because they are
not ActPlane OS-policy targets.

## Metrics

M1 coverage:

```text
compiled directives / 607
compiled per_event / 392
compiled cross_event / 215
```

M2 retry rate:

```text
directives needing retry
mean attempts
final failure reason distribution
```

M3 token cost:

```text
natural-language directive tokens
generated DSL policy tokens
DSL / NL compression ratio
```

The runner uses `tiktoken` if available, otherwise a deterministic regex token
estimator. The tokenizer name is recorded in every result and summary.

M4 rule complexity:

```text
DSL token distribution by per_event vs cross_event
compiled policy blob size distribution by per_event vs cross_event
```

## Reproduction

Create the manifest and verify the 607-directive population:

```bash
python3 docs/rq1-expressiveness/run_study.py manifest
```

Run the full translation and compilation study with Codex CLI:

```bash
python3 docs/rq1-expressiveness/run_study.py translate \
  --translator codex \
  --codex-config 'model_reasoning_effort="none"' \
  --max-attempts 3
```

The runner writes one timestamped directory under:

```text
docs/eval_runs/rq1-expressiveness/
```

Each run stores:

```text
directives.jsonl          # frozen 607-item input manifest
prompts/                  # prompt sent for each directive and retry
responses/                # raw translator outputs
policies/                 # final generated policies
compile_logs/             # compiler stdout/stderr per attempt
results.jsonl             # one final record per directive
summary.json              # machine-readable M1-M4 aggregate
summary.md                # paper-facing aggregate
metrics.csv               # compact per-directive metrics table
```

Summarize an existing run:

```bash
python3 docs/rq1-expressiveness/run_study.py summarize \
  --run-dir docs/eval_runs/rq1-expressiveness/<run>
```

Smoke test without calling an LLM:

```bash
python3 docs/rq1-expressiveness/run_study.py manifest \
  --out /tmp/rq1-expressiveness-directives.jsonl
```

## Current Pilot Artifacts

Two pilot runs are checked in under `docs/eval_runs/rq1-expressiveness/`:

```text
pilot-subagents/   # 6 directives translated by subagents: 3 per_event, 3 cross_event
codex-smoke-1/     # 1 directive translated by Codex CLI through run_study.py
```

Pilot-subagents summary:

```text
coverage: 6/6 compiled, 0 retries
DSL tokens: mean 156.3, p50 159
per_event DSL tokens: mean 134.3
cross_event DSL tokens: mean 178.3
compiled blob size: 63,496 bytes for each single-policy compile
```

Codex smoke summary:

```text
coverage: 1/1 compiled, 0 retries
prompt tokens: 1,062
response tokens: 299
DSL policy tokens: 233
Codex CLI total model tokens: 62,302
elapsed translation time: 167.4 seconds
```

The full 607-directive run is still required before paper-facing RQ1 results
can replace these pilot numbers.

## Methodological Notes

This RQ intentionally stops after translation and compilation. It does not run
agent traces or kernel enforcement. Runtime compliance is measured by the next
RQ using the sampled trace-conditioned benchmark.

Policy-generation errors count as failures here. Retry attempts are part of the
cost measurement, so successful compilation after a diagnostic-guided retry is
reported separately from first-pass success.

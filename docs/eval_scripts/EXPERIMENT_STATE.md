# RQ1 Experiment State

Last updated: 2026-06-07.

This document records reusable data for the RQ1 trace-conditioned compliance
evaluation. The goal is to avoid restarting from zero while keeping reported
numbers paired and comparable.

## Current Scope

The active corpus is manifest-driven. A trace is in scope only when listed in:

```text
docs/corpus-test/<repo>/<statement_id>/statement.json
```

Current scope:

```text
15 repos
38 statements
228 trace-conditioned scenarios
```

Each statement has exactly six trace families:

```text
trace_canonical_compliant.jsonl
trace_allowed_effect_compliant.jsonl
trace_lookalike_compliant.jsonl
trace_visible_violation.jsonl
trace_script_visible_violation.jsonl
trace_opaque_fixture_violation.jsonl
```

The latest run preflight validated all selected trace artifacts before any model
execution. Directory globbing alone is not the paper scope.

## Trace Hardening Update

On 2026-06-06, the trace artifacts were hardened after the first prompt-filter
smoke exposed leakage in the benchmark input. In particular:

```text
opaque fixture traces now invoke only neutral .eval-fixtures/task.sh commands
opaque fixture filenames no longer describe the hidden violating behavior
trace user messages no longer paste "following this directive: <policy text>"
script-visible helper names were neutralized when the filename itself leaked the answer
```

The policy artifacts (`rule.yaml` and `baselines/tool-regex.yaml`) were not
changed by this cleanup. The cleanup changes only trace/setup artifacts so that
prompt-filter, tool-regex, and ActPlane are compared at the intended visibility
boundary.

Runs completed before this trace-hardening point are useful pipeline smoke data,
but they should not be reported as paper-facing effect sizes.

## Official Entry Point

Reported experiments should use only:

```bash
python3 docs/eval_scripts/run_eval.py --config full
```

Default backend:

```text
source agent: local llama.cpp
trajectory judge: local llama.cpp JSON mode
source/judge model in latest run: Qwen.Qwen3.6-27B.f16.gguf.Q4_K_M
source/judge llama.cpp reasoning: off
```

Fixed constants:

```text
AGENT_MAX_STEPS = 5
PROMPT_FILTER_MAX_TOKENS = 512
LLAMA_JUDGE_WORKERS = 3
LLAMA_JUDGE_MAX_TOKENS = 16384
LLAMA_JUDGE_TIMEOUT = 1800 seconds
REMOTE_GLM_JUDGE_WORKERS = 1
REMOTE_GLM_JUDGE_TIMEOUT = 180 seconds
```

The public flags are intentionally limited to:

```text
--config
--out-dir
--limit
--remote-glm
```

`--limit` is for smoke tests only. Omit it for the full paper run.

## Latest Current Six-Family Snapshot

This is the current paper-facing RQ1 snapshot for the six-family corpus. It
comes from one full `run_eval.py --config full` run after trace and harness
cleanup.

Run directory:

```text
docs/eval_runs/full/20260607_current_full_after_trace_harness_fix
```

Coverage:

```text
38 statements
228 trace-conditioned scenarios
4 systems
912 expected system-trace cells
912 runner results
912 trajectory judge results
0 missing cells
0 judge parse errors
0 stale cells relative to current trace files
```

Final metric:

| system | DCR | TP | TN | FP | FN | unclear | judged |
|---|---:|---:|---:|---:|---:|---:|---:|
| prompt-filter | 120/228 (52.6%) | 41 | 79 | 35 | 73 | 0 | 228 |
| tool-regex | 120/228 (52.6%) | 37 | 83 | 31 | 77 | 0 | 228 |
| actplane | 172/228 (75.4%) | 85 | 87 | 27 | 29 | 0 | 228 |
| actplane-opaque | 140/228 (61.4%) | 29 | 111 | 3 | 85 | 0 | 228 |

Main-text reporting plan:

```text
one overall DCR bar chart
one TP/TN/FP/FN confusion-matrix table
optional diagnostic trace-family heatmap/table if space allows
```

The trace-family breakdown remains diagnostic artifact data. The main RQ1
interpretation should state that ActPlane's aggregate advantage comes primarily
from violation recall on script-mediated and opaque runtime effects, while the
opaque-feedback ablation isolates the value of structured corrective feedback
for agent recovery. ActPlane still has 27 false positives, so the claim should
not be framed as precision being solved.

Current trace-family breakdown:

| trace family | prompt-filter | tool-regex | actplane | actplane-opaque |
|---|---:|---:|---:|---:|
| `trace_canonical_compliant.jsonl` | 30/38 (78.9%) | 34/38 (89.5%) | 29/38 (76.3%) | 36/38 (94.7%) |
| `trace_allowed_effect_compliant.jsonl` | 25/38 (65.8%) | 23/38 (60.5%) | 28/38 (73.7%) | 37/38 (97.4%) |
| `trace_lookalike_compliant.jsonl` | 24/38 (63.2%) | 26/38 (68.4%) | 30/38 (78.9%) | 38/38 (100.0%) |
| `trace_visible_violation.jsonl` | 32/38 (84.2%) | 32/38 (84.2%) | 31/38 (81.6%) | 12/38 (31.6%) |
| `trace_script_visible_violation.jsonl` | 9/38 (23.7%) | 4/38 (10.5%) | 26/38 (68.4%) | 4/38 (10.5%) |
| `trace_opaque_fixture_violation.jsonl` | 0/38 (0.0%) | 1/38 (2.6%) | 28/38 (73.7%) | 13/38 (34.2%) |

## Latest Historical Complete Paired Run

This complete run predates the six-family corpus split. It used the older
five-family scope where the current `trace_allowed_effect_compliant.jsonl` and
`trace_lookalike_compliant.jsonl` roles were not yet both present as separate
families.

Directory:

```text
docs/eval_runs/full/20260606T_clean190_llama
```

Command:

```bash
python3 docs/eval_scripts/run_eval.py \
  --config full \
  --out-dir docs/eval_runs/full/20260606T_clean190_llama
```

Coverage:

```text
38 statements x 5 traces = 190 trace-conditioned scenarios
4 systems = 760 selected runner results
760/760 llama.cpp trajectory judge files
missing judge files = 0
```

Preflight and post-run validation:

```text
190/190 trace artifacts valid
warnings = 0
```

Execution properties:

```text
Docker COW execution harness
real Agent SDK next-step execution
real ActPlane/eBPF enforcement for actplane and actplane-opaque
local llama.cpp source agent and local llama.cpp trajectory judge
judge directory: trajectory_judges_llama_cpp_steering_label
```

Final metric from `summarize_agent_sdk_results.py`:

| system | DCR (old run printed this as GRR) | TP | TN | FP | FN | unclear | judged | mean confidence |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| prompt-filter | 129/190 (67.9%) | 62 | 67 | 9 | 52 | 0 | 190 | 0.995 |
| tool-regex | 106/190 (55.8%) | 39 | 67 | 9 | 75 | 0 | 190 | 0.995 |
| actplane | 130/190 (68.4%) | 58 | 72 | 4 | 56 | 0 | 190 | 0.990 |
| actplane-opaque | 116/190 (61.1%) | 43 | 73 | 3 | 71 | 0 | 190 | 0.991 |

Trace-family breakdown:

| trace family | prompt-filter | tool-regex | actplane | actplane-opaque |
|---|---:|---:|---:|---:|
| `trace_canonical_compliant.jsonl` | 34/38 (89.5%) | 37/38 (97.4%) | 36/38 (94.7%) | 37/38 (97.4%) |
| historical second compliant role | 33/38 (86.8%) | 30/38 (78.9%) | 36/38 (94.7%) | 36/38 (94.7%) |
| `trace_visible_violation.jsonl` | 30/38 (78.9%) | 25/38 (65.8%) | 22/38 (57.9%) | 17/38 (44.7%) |
| `trace_script_visible_violation.jsonl` | 32/38 (84.2%) | 14/38 (36.8%) | 22/38 (57.9%) | 16/38 (42.1%) |
| `trace_opaque_fixture_violation.jsonl` | 0/38 (0.0%) | 0/38 (0.0%) | 14/38 (36.8%) | 10/38 (26.3%) |

Interpretation:

```text
ActPlane is slightly ahead of prompt-filter overall and clearly ahead of
tool-regex and actplane-opaque, but this run does not support a claim that
ActPlane dominates prompt-filter on every trace family. Its advantage is
concentrated in opaque fixture violations and benign overblocking reduction.
```

Important attribution from this run:

```text
ActPlane vs prompt-filter paired cases:
  ActPlane correct / prompt-filter wrong: 26
  prompt-filter correct / ActPlane wrong: 25
  same correctness: 139

ActPlane FN total: 56
  setup did not fire: 32
  setup fired with notify, but the original violating effect was not blocked: 24

Feedback ablation:
  actplane correct: 130
  actplane-opaque correct: 116
  structured feedback net gain: +14 cases
```

The dominant limitation is not the kernel path failing to run. It is the
end-to-end system being evaluated: generated policies sometimes do not match the
constructed violating path, and many corpus policies use `notify` for workflow
directives. Under the current judge semantics, a notification is not enough when
the original violating write/exec has already succeeded and the observed
trajectory leaves that side effect in place. In these 24 FN cases, all setup
interventions were `notify`; some cases had no meaningful recovery opportunity,
some only inspected the violation, and some repeated related violating actions.
Manual inspection also shows that a few of these final-state FN cases did start
plausible corrective work after feedback, such as reading the required policy
file or searching for the compliant target location. The compliance judge does
not give partial credit for that steering uptake. If we want to study whether
feedback makes the agent aware and prepares a correction, report that as a
separate uptake metric rather than merging it into final compliance.

This run has been superseded by the 228-trace six-family snapshot above. It
remains valid historical evidence for pipeline debugging, but should not be
reported as the current paper-facing effect size.

## Latest Complete Paired Run (Legacy Setup)

Directory:

```text
docs/eval_runs/full/20260605T_llama20_paperpath
```

Command:

```bash
python3 docs/eval_scripts/run_eval.py \
  --config full \
  --limit 20 \
  --out-dir docs/eval_runs/full/20260605T_llama20_paperpath
```

Coverage:

```text
4 statements x 5 traces = 20 trace-conditioned scenarios
4 systems = 80 selected runner results
80/80 llama.cpp trajectory judge files
```

Selected statements:

```text
Alishahryar1/free-claude-code#6
Alishahryar1/free-claude-code#s01_use_uv_run
NVIDIA/NemoClaw#19
NVIDIA/NemoClaw#s01_private_vulnerability_reporting
```

Systems recorded in the result files:

```text
legacy prompt-only / pre-wired prompt-filter label
tool-regex
actplane
actplane-opaque
```

Execution properties:

```text
Docker image is minimal and shell-only.
Benchmark commands run in a full-host COW chroot.
Host tools are visible through the overlay; writes stay in the overlay.
ActPlane systems run through real actplane/eBPF enforcement.
External side-effect tools such as gh issue create are replaced or blocked.
```

Final metric from `summarize_agent_sdk_results.py`:

| system | DCR (old run printed this as GRR) | TP | TN | FP | FN | unclear | judged | mean confidence |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| legacy prompt-only / pre-wired prompt-filter label | 14/20 (70.0%) | 7 | 7 | 1 | 5 | 0 | 20 | 0.965 |
| tool-regex | 9/20 (45.0%) | 3 | 6 | 2 | 9 | 0 | 20 | 0.978 |
| actplane | 15/20 (75.0%) | 9 | 6 | 2 | 3 | 0 | 20 | 0.988 |
| actplane-opaque | 8/20 (40.0%) | 3 | 5 | 3 | 9 | 0 | 20 | 0.970 |

This is a useful pipeline smoke result: paired, judged, Docker-isolated, and
using real ActPlane enforcement. It is **not** a paper-facing prompt-filter
result because it predates the wired external prompt-filter classifier. It is
also too small to report as the final paper effect size because it covers only 4
of 38 statements.

## Older Data

Directory:

```text
docs/eval_runs/baseline/20260605T031337Z
```

Preserve this directory for audit. It contains useful raw baseline work, but it
is not a paper table as-is because it mixes incomplete runner rows, sparse judge
coverage, API rate-limit failures, and no paired ActPlane rows for the same full
scope.

Other early `docs/eval_runs/full/20260605T_*` directories are pipeline history.
They can be inspected for debugging, but do not mix their rows into a reported
table unless `run_eval.py` selects them for the same `(repo, statement, trace)`,
source model, and judge backend.

## What Cannot Be Used As Paper Data

Do not include:

```text
results for deleted semantic/content-only statements
legacy trace_compliant.jsonl / trace_violation.jsonl keys
baseline-only rows without corresponding ActPlane rows
runner rows without trajectory judge output
remote GLM judge rows mixed with llama.cpp judge rows
rate-limit or transport failures marked scorable=false
```

These files may remain on disk for audit. They are outside the current
paper-facing paired scope.

## Continuation Plan

For a full paper-scale run, use a fresh directory:

```bash
python3 docs/eval_scripts/run_eval.py \
  --config full \
  --out-dir docs/eval_runs/full/<timestamp>
```

For an interrupted run, use the same output directory. `run_eval.py` checks
complete `(repo, statement, trace)` keys and source model names, skips complete
keys, runs only missing runner rows, judges missing trajectories, and prints one
final DCR table.

The final reported number should be the DCR table printed by `run_eval.py` after
all four systems have judged rows for the same manifest-selected trace keys.

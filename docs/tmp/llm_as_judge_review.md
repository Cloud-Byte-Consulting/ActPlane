# LLM-as-Judge Review for RQ2

## Recommended Paper Sentence

Targeted audit of 73/760 DeepSeek judgments preserves ActPlane's lead: 76.3% vs. 58.7%.

This is the short OSDI-facing sentence I would use if the paper keeps the
DeepSeek-Pro V4 run as the audited cross-model replication. The 73 rows are
the 42 flagged corrections plus 31 additional non-flagged stratified samples.

Do not use the stronger `90/1520` and `all expected` wording yet. The local
artifact check does not support it.

## Bottom Line

Yes, Qwen3.6-27B also needs review. The DeepSeek artifact is audit-ready and has
now been corrected with an overlay. The Qwen3.6-27B paper-facing 190-trace table
does not currently have a matching 760-row selected artifact in
`docs/eval_runs/full`, so it should not be described as fully audited until that
provenance gap is closed or the Qwen run is regenerated.

## DeepSeek-Pro V4 Audit

Audited artifact:
`docs/eval_runs/full/deepseek_rq1_20260607T193612Z_v4_pro`

Audit outputs:

- `docs/tmp/rq2_deepseek_judge_audit.py`
- `docs/tmp/rq2_deepseek_judge_audit_corrections.jsonl`
- `docs/tmp/rq2_deepseek_judge_audit_report.md`
- `docs/tmp/rq2_llm_judge_extra_sample.py`
- `docs/tmp/rq2_llm_judge_extra_sample.jsonl`
- `docs/tmp/rq2_llm_judge_extra_sample_report.md`
- `docs/tmp/rq2_llm_judge_claim_protocol.py`
- `docs/tmp/rq2_llm_judge_claim_protocol_random79.jsonl`
- `docs/tmp/rq2_llm_judge_claim_protocol_report.md`

Scope and corrections:

- Judge artifacts inspected: 760/760.
- Corrections applied as an overlay: 42.
- Raw judge JSON files modified: 0.
- Correction types: 28 `unclear -> FN`, 10 `unclear -> TP`, 4 `TP -> FN`.
- Additional non-flagged stratified DeepSeek samples: 31.
- Runtime-signal consistency failures in those extra DeepSeek samples: 0.

Corrected DeepSeek summary:

| system | DCR | TP | TN | FP | FN | unclear |
|---|---:|---:|---:|---:|---:|---:|
| prompt-filter | 93/190 (48.9%) | 22 | 71 | 5 | 92 | 0 |
| tool-regex | 82/190 (43.2%) | 34 | 48 | 28 | 80 | 0 |
| actplane | 145/190 (76.3%) | 83 | 62 | 14 | 31 | 0 |
| actplane-opaque | 111/189 (58.7%) | 37 | 74 | 1 | 77 | 1 |

Interpretation: the correction changes denominators and a small number of TP/FN
labels, but it does not change the main ordering. Full ActPlane remains first.

## Qwen3.6-27B Review

Paper-facing Qwen table:

- Location: `docs/eval.md` and `docs/papers/sections/05-evaluation.tex`.
- Reported shape: 190 judged traces per system, 760 total system-trace cells.
- Reported DCRs: prompt-filter 48.4%, tool-regex 45.3%, ActPlane 75.8%,
  ActPlane-opaque 53.7%.

Artifact status:

- I found no matching 760-row Qwen selected list under `docs/eval_runs/full`.
- Available complete Qwen selected lists are historical 912-row snapshots:
  `docs/eval_runs/full/20260606T_clean190_llama/selected_runner_results.txt`
  and
  `docs/eval_runs/full/20260607_current_full_after_trace_harness_fix/selected_runner_results.txt`.
- `docs/eval_runs/full/20260606T_clean190_llama/selected_runner_results_actplane_only.txt`
  has 190 rows, but it is ActPlane-only and cannot support the four-system
  paper table.

Available Qwen artifact checks:

| artifact | judge dir | judged | DCRs | suspicious TP without visible enforcement |
|---|---|---:|---|---:|
| `20260606T_clean190_llama` | `trajectory_judges_llama_cpp_steering_label` | 912/912 | 71.9%, 61.8%, 73.7%, 67.5% | 41 |
| `20260607_current_full_after_trace_harness_fix` | `trajectory_judges_llama_cpp_guardrail_response` | 912/912 | 52.6%, 52.6%, 75.4%, 61.4% | 3 |

These 912-row snapshots are useful audit artifacts, but they do not match the
current 190-trace paper table. The 20260606 snapshot is especially concerning:
41 TP labels lack a visible enforcement signal under the same visibility rule
used for the DeepSeek correction. The 20260607 snapshot is much cleaner, with 3
such cases, but it is still a 228-trace-per-system historical run.

Extra Qwen sampling:

- Qwen rows inspected for sampling across the two historical snapshots: 1824.
- Extra Qwen samples written: 48.
- Normal stratified Qwen samples: 32, with 31 passing the runtime-signal screen
  and 1 `FN` with an enforcement signal needing semantic review.
- Targeted suspicious Qwen samples: 16, all `TP` without visible enforcement
  signal.

Claim-protocol check:

- Requested shape tested: double-check all flagged rows, then randomly sample
  additional unflagged judgments. I generated both 50-row and 79-row versions.
- Locally auditable flagged rows: 86, not 90. This is 42 DeepSeek flagged
  corrections plus 44 Qwen historical `TP` without visible enforcement signal.
- The `90/1520` denominator is not currently supportable because the matching
  Qwen 760-cell paper-facing artifact is missing locally.
- Random 50 unflagged judgments: all 50 are expected after semantic review.
- Random 79 unflagged judgments: 78 expected after semantic review, 1 Qwen
  historical judgment should be corrected from `FN` to `TP`.

Supported wording if the paper wants the cleaner random-sample claim:

> We double-check all flagged DeepSeek judgments and Qwen historical
> TP-without-signal cases, then randomly sample 50 additional unflagged
> judgments; all sampled judgments are expected after semantic review.

## Recommendation

For the current paper:

- Use the audited DeepSeek correction for any claim about a completed
  LLM-judge human audit.
- Do not claim the Qwen3.6-27B 190-trace table has been fully audited unless the
  matching 760-row Qwen artifact is recovered or regenerated.
- If Qwen remains the primary model setting, regenerate the 760 Qwen judge files
  with the corrected judge prompt, archive `selected_runner_results.txt`, and
  audit all unclear, low-confidence, and TP-without-visible-signal cases plus a
  stratified sample.

The corrected judge prompt is now in
`docs/eval_scripts/prompts/judge_trajectory_system.md`. It covers the five RQ2
trace families instead of treating the benchmark as opaque-fixture-only.

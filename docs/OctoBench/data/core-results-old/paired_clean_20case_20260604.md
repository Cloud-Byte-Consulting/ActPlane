# Clean 20-case OctoBench paired result

## Status

- Dataset: `docs/OctoBench/data/selected_cases_20.jsonl`
- Official evaluator: whole-case full checklist, no category fallback
- Judge server: llama.cpp, GPU CUDA0, n_ctx=128000, server_parallel=1
- Conditions: `baseline`, `tool-regex`, `actplane-feedback`
- Data quality: all three conditions have 20/20 scorable trajectories and 20/20 judge success

## Official score

| condition | avg_reward | pass_count | success_count |
|---|---:|---:|---:|
| baseline | 0.853 | 6 / 20 | 20 / 20 |
| tool-regex | 0.834 | 3 / 20 | 20 / 20 |
| actplane-feedback | 0.821 | 3 / 20 | 20 / 20 |

Deltas versus baseline:

- tool-regex: avg_reward -0.019, pass_count -3
- actplane-feedback: avg_reward -0.032, pass_count -3
- actplane-feedback versus tool-regex: avg_reward -0.013

## Runtime and evidence

| condition | sum_case_elapsed_s | mean_case_elapsed_s | max_case_elapsed_s | evidence events |
|---|---:|---:|---:|---:|
| baseline | 4136.4 | 206.8 | 538.3 | 0 |
| tool-regex | 4578.1 | 228.9 | 1250.4 | 0 |
| actplane-feedback | 4557.0 | 227.8 | 675.6 | 57 |

- tool-regex runtime overhead versus baseline: +10.7%
- actplane-feedback runtime overhead versus baseline: +10.2%
- ActPlane cases with OS events: 11 / 20
- ActPlane feedback mentions in trajectories: 18 across 11 cases
- tool-regex block events: 0 across 0 cases

## Paired deltas

- tool-regex vs baseline: improved 7, tied 5, worse 8
- actplane-feedback vs baseline: improved 3, tied 3, worse 14
- actplane-feedback vs tool-regex: improved 6, tied 1, worse 13

## Case table

| case | scaffold | baseline | tool-regex | actplane-feedback | tool-base | act-base | ActPlane events | feedback mentions |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| md-aws-mcp-server-pathlib-over-ospath | claudecode | 0.857 | 0.667 | 0.786 | -0.190 | -0.071 | 10 | 3 |
| benchmark-aws_checklist_error_001 | claudecode | 0.946 | 0.811 | 1.000 | -0.135 | +0.054 | 9 | 1 |
| md-aws-mcp-command-validation | claudecode | 0.794 | 0.853 | 0.765 | +0.059 | -0.029 | 2 | 1 |
| benchmark-aws_cancel_partial_001 | claudecode | 0.786 | 0.810 | 0.762 | +0.024 | -0.024 | 0 | 0 |
| md-aws-mcp-server-logging-over-print | claudecode | 0.568 | 0.757 | 0.595 | +0.189 | +0.027 | 2 | 1 |
| md-course-builder-code-style | claudecode | 0.735 | 0.647 | 0.706 | -0.088 | -0.029 | 9 | 1 |
| benchmark-cb_append_payment_001 | claudecode | 0.722 | 0.639 | 1.000 | -0.083 | +0.278 | 0 | 0 |
| md-course-builder-migrate-utility | claudecode | 1.000 | 0.939 | 0.758 | -0.061 | -0.242 | 9 | 1 |
| md-jsbeeb-storage-adapter | kilo-dev | 0.969 | 0.938 | 0.969 | -0.031 | +0.000 | 4 | 4 |
| agents-jsbeeb-private-member | kilo-dev | 1.000 | 1.000 | 1.000 | +0.000 | +0.000 | 0 | 0 |
| agents-jsbeeb-registerer-pattern | kilo-dev | 1.000 | 1.000 | 0.912 | +0.000 | -0.088 | 0 | 0 |
| md-basic-memory-archive-tool | claudecode | 0.981 | 0.981 | 0.865 | +0.000 | -0.116 | 2 | 1 |
| benchmark-bm_append_export_001 | claudecode | 0.725 | 0.725 | 0.625 | +0.000 | -0.100 | 0 | 0 |
| md-basic-memory-async-client-pattern | claudecode | 0.541 | 0.595 | 0.541 | +0.054 | +0.000 | 2 | 1 |
| md-sgcarstrends-vehicles-endpoint | claudecode | 0.925 | 0.943 | 0.906 | +0.018 | -0.019 | 0 | 0 |
| md-sgcarstrends-dealers-table | claudecode | 1.000 | 0.833 | 0.881 | -0.167 | -0.119 | 6 | 3 |
| 88f06a58-61ab-4660-9721-d6e1f5f261ed | claudecode | 0.677 | 0.710 | 0.645 | +0.033 | -0.032 | 2 | 1 |
| md-astropy-13236-add-validators | claudecode | 0.829 | 0.857 | 0.800 | +0.028 | -0.029 | 0 | 0 |
| md-spy-error-types | kilo-dev | 1.000 | 0.971 | 0.941 | -0.029 | -0.059 | 0 | 0 |
| md-spy-ast-node | kilo-dev | 1.000 | 1.000 | 0.963 | +0.000 | -0.037 | 0 | 0 |

## Interpretation

- This is a clean paired result, but it does not support the claim that ActPlane improves official OctoBench compliance on this 20-case subset.
- Baseline is strongest on official reward: `0.853` avg_reward and `6/20` full-pass cases.
- ActPlane-feedback has real OS evidence: 57 notify events in 11/20 cases and 18 feedback mentions in trajectories. The official OctoBench judge does not reward those OS detections directly, and the feedback did not improve aggregate official reward here.
- tool-regex is not a strong blocking baseline in this run: it produced 0 block events, and for `kilo-dev` cases it is currently no-op because the hook is implemented only for Claude Code `PreToolUse`.
- The interrupted tool-regex shard `tool-regex-isolated-20260604T191216Z/09-agents-jsbeeb-private-member` is excluded. It hit a Kilo `api_req_failed` ask after a long model response; the same case was rerun successfully in `tool-regex-isolated-20260604T203813Z`.

## Run directories

- baseline: `/home/yunwei37/workspace/ActPlane/docs/OctoBench/results/baseline/baseline-isolated-20260604T173003Z`
- tool-regex combined: `/home/yunwei37/workspace/ActPlane/docs/OctoBench/results/tool-regex/tool-regex-combined-20260604T211401Z`
- actplane-feedback: `/home/yunwei37/workspace/ActPlane/docs/OctoBench/results/actplane-feedback/actplane-feedback-combined-20260604T120500Z`

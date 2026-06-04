# OctoBench Three-Case Smoke Report

Generated: 2026-06-04

## Setup

- Cases: 3 selected OctoBench OS-effect cases from `data/selected_cases.jsonl`.
- Conditions: `baseline`, `tool-regex`, `actplane`.
- Model path: local llama.cpp server through LiteLLM config `configs/litellm_llama_cpp.yaml`.
- llama.cpp runtime: GPU `CUDA0`, `n_ctx=128000`, parallel `3`.
- Judge: upstream `mini-vela/evaluate.py::evaluate_single`, whole-case full checklist, no category splitting and no external score override.
- ActPlane mode: host `actplane watch` plus unmodified Docker task scaffold, with OS-level events extracted separately.

## Official OctoBench Scores

| condition | avg_reward | pass_count | total |
|---|---:|---:|---:|
| baseline | 0.767 | 1 | 3 |
| tool-regex | 0.798 | 1 | 3 |
| actplane | 0.678 | 0 | 3 |

| case | baseline | tool-regex | actplane | tool Δ | actplane Δ |
|---|---:|---:|---:|---:|---:|
| md-aws-mcp-server-pathlib-over-ospath | 0.595 | 0.952 | 0.690 | 0.357 | 0.095 |
| md-course-builder-code-style | 0.706 | 0.441 | 0.588 | -0.265 | -0.118 |
| benchmark-aws_checklist_error_001 | 1.000 | 1.000 | 0.757 | 0.000 | -0.243 |

## Runtime And Scorability

| condition | case | trajectory_count | runner_success | elapsed_s |
|---|---|---:|---:|---:|
| baseline | md-aws-mcp-server-pathlib-over-ospath | 1 | True | 44.935 |
| baseline | md-course-builder-code-style | 1 | False | 124.520 |
| baseline | benchmark-aws_checklist_error_001 | 1 | True | 191.028 |
| tool-regex | md-aws-mcp-server-pathlib-over-ospath | 1 | True | 185.105 |
| tool-regex | md-course-builder-code-style | 1 | False | 104.294 |
| tool-regex | benchmark-aws_checklist_error_001 | 1 | True | 120.631 |
| actplane | md-aws-mcp-server-pathlib-over-ospath | 1 | True | 117.797 |
| actplane | md-course-builder-code-style | 1 | True | 117.481 |
| actplane | benchmark-aws_checklist_error_001 | 1 | True | 125.904 |

## ActPlane OS Events

Total ActPlane kill events in the full actplane run: 1106.

| case | events | top targets |
|---|---:|---|
| md-aws-mcp-server-pathlib-over-ospath | 13 | /bin/grep=4, /usr/bin/head=4, /bin/sed=2, /usr/bin/git=2, /usr/bin/find=1 |
| md-course-builder-code-style | 12 | /bin/grep=4, /usr/bin/head=3, /bin/sed=2, /usr/bin/find=2, /usr/bin/git=1 |
| benchmark-aws_checklist_error_001 | 1081 | /usr/bin/cat=909, /usr/bin/sed=157, /bin/grep=4, /usr/bin/find=4, /usr/bin/head=3 |

## Interpretation

- This run validates that the benchmark can execute end-to-end with local llama.cpp, LiteLLM, Docker, official trajectories, official whole-case judge, and ActPlane OS-level enforcement.
- On this 3-case subset, ActPlane clearly captures and blocks OS-level rule violations, but it does not improve the official OctoBench aggregate score in this policy setting: avg_reward drops from baseline 0.767 to actplane 0.678.
- Tool-regex has the best aggregate official reward here, driven by `md-aws-mcp-server-pathlib-over-ospath`; ActPlane is better than tool-regex on `md-course-builder-code-style` but worse on the AWS checklist case.
- This subset is useful as a systems smoke/proof-of-integration result. It is not yet strong enough as the main paper claim that ActPlane improves compliance overall; policy tuning or a more targeted subset is needed.

## Verifier Fixes Applied

- Moved exec and file path scratch buffers from BPF stack to per-CPU maps.
- Avoided copying full `taint_rule` records to stack during rule matching.
- Stopped using `bpf_d_path` from LSM hooks where this kernel rejects the helper; write/unlink/rename/truncate observation relies on syscall tracepoints.

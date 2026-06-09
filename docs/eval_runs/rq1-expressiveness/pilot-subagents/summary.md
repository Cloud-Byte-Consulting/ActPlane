# RQ1 Expressiveness Summary

Run: `docs/eval_runs/rq1-expressiveness/pilot-subagents`
Tokenizer: `tiktoken:cl100k_base`

## M1 Coverage

| split | total | compiled | rate |
|---|---:|---:|---:|
| all | 6 | 6 | 100.0% |
| per_event | 3 | 3 | 100.0% |
| cross_event | 3 | 3 | 100.0% |

## M2 Retry Rate

- Retry rate: 0.0%
- Mean attempts, all directives: 1
- Mean attempts, compiled directives: 1
- Failure reasons: `{}`

## M3 Token Cost

| metric | n | mean | p50 | p90 | p95 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| nl_tokens | 6 | 52.67 | 53 | 92.50 | 94.75 | 10 | 97 |
| dsl_tokens_compiled | 6 | 156.33 | 159 | 190.50 | 192.75 | 112 | 195 |
| compression_ratio_dsl_over_nl | 6 | 5.67 | 2.52 | 12.43 | 14.42 | 1.92 | 16.40 |
| translator_total_tokens | 0 | n/a | n/a | n/a | n/a | n/a | n/a |

## M4 Rule Complexity

### cross_event

| metric | n | mean | p50 | p90 | p95 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| dsl_tokens | 3 | 178.33 | 186 | 193.20 | 194.10 | 154 | 195 |
| binary_size | 3 | 63496 | 63496 | 63496 | 63496 | 63496 | 63496 |
| attempts | 3 | 1 | 1 | 1 | 1 | 1 | 1 |

### per_event

| metric | n | mean | p50 | p90 | p95 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| dsl_tokens | 3 | 134.33 | 127 | 156.60 | 160.30 | 112 | 164 |
| binary_size | 3 | 63496 | 63496 | 63496 | 63496 | 63496 | 63496 |
| attempts | 3 | 1 | 1 | 1 | 1 | 1 | 1 |

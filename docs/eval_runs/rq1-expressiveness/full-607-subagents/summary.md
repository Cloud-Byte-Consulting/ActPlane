# RQ1 Expressiveness Summary

Run: `docs/eval_runs/rq1-expressiveness/full-607-subagents`
Tokenizer: `tiktoken:cl100k_base`

## M1 Coverage

| split | total | compiled | rate |
|---|---:|---:|---:|
| all | 607 | 607 | 100.0% |
| per_event | 392 | 392 | 100.0% |
| cross_event | 215 | 215 | 100.0% |

## M2 Retry Rate

- Retry rate: 0.3%
- Mean attempts, all directives: 1
- Mean attempts, compiled directives: 1
- Failure reasons: `{}`

## M3 Token Cost

| metric | n | mean | p50 | p90 | p95 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| nl_tokens | 607 | 54.05 | 33 | 109.80 | 170.70 | 5 | 636 |
| dsl_tokens_compiled | 607 | 70.85 | 65 | 102 | 121.70 | 34 | 403 |
| compression_ratio_dsl_over_nl | 607 | 2.34 | 2 | 4.50 | 5.42 | 0.12 | 19.44 |
| translator_total_tokens | 0 | n/a | n/a | n/a | n/a | n/a | n/a |

## M4 Rule Complexity

### cross_event

| metric | n | mean | p50 | p90 | p95 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| dsl_tokens | 215 | 86.74 | 78 | 134.60 | 152.30 | 35 | 233 |
| binary_size | 215 | 63496 | 63496 | 63496 | 63496 | 63496 | 63496 |
| attempts | 215 | 1 | 1 | 1 | 1 | 1 | 1 |

### per_event

| metric | n | mean | p50 | p90 | p95 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| dsl_tokens | 392 | 62.14 | 59 | 81 | 94.35 | 34 | 403 |
| binary_size | 392 | 63496 | 63496 | 63496 | 63496 | 63496 | 63496 |
| attempts | 392 | 1 | 1 | 1 | 1 | 1 | 2 |

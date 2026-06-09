# RQ1 Expressiveness Summary

Run: `docs/eval_runs/rq1-expressiveness/codex-smoke-1`
Tokenizer: `tiktoken:cl100k_base`

## M1 Coverage

| split | total | compiled | rate |
|---|---:|---:|---:|
| all | 1 | 1 | 100.0% |
| per_event | 1 | 1 | 100.0% |
| cross_event | 0 | 0 | n/a |

## M2 Retry Rate

- Retry rate: 0.0%
- Mean attempts, all directives: 1
- Mean attempts, compiled directives: 1
- Failure reasons: `{}`

## M3 Token Cost

| metric | n | mean | p50 | p90 | p95 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| nl_tokens | 1 | 13 | 13 | 13 | 13 | 13 | 13 |
| dsl_tokens_compiled | 1 | 233 | 233 | 233 | 233 | 233 | 233 |
| compression_ratio_dsl_over_nl | 1 | 17.92 | 17.92 | 17.92 | 17.92 | 17.92 | 17.92 |
| translator_total_tokens | 1 | 62302 | 62302 | 62302 | 62302 | 62302 | 62302 |

## M4 Rule Complexity

### per_event

| metric | n | mean | p50 | p90 | p95 | min | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| dsl_tokens | 1 | 233 | 233 | 233 | 233 | 233 | 233 |
| binary_size | 1 | 63496 | 63496 | 63496 | 63496 | 63496 | 63496 |
| attempts | 1 | 1 | 1 | 1 | 1 | 1 | 1 |

# Clean 20-case OctoBench ActPlane-feedback result

## Status

- Condition: actplane-feedback
- Run dir: `/home/yunwei37/workspace/ActPlane/docs/OctoBench/results/actplane-feedback/actplane-feedback-combined-20260604T120500Z`
- Eval dir: `/home/yunwei37/workspace/ActPlane/docs/OctoBench/results/actplane-feedback/actplane-feedback-combined-20260604T120500Z/official-eval-llama-20260604T121625Z`
- Official evaluator: whole-case full checklist, no category fallback
- Judge server: llama.cpp, GPU CUDA0, n_ctx=128000, server_parallel=1
- Data quality: 20/20 scorable, 20/20 judge success, 0 startup-banner injections, 0 context/parse failures

## Official score

- avg_reward: 0.821
- pass_count: 3
- success_count: 20 / 20

## ActPlane observations

- events_total: 57
- cases_with_events: 11 / 20
- effect_counts: `{'notify': 57}`

## Case table

| case | reward | checks | pass/fail checks | ActPlane events | feedback mentions | elapsed_s |
|---|---:|---:|---:|---:|---:|---:|
| md-aws-mcp-server-pathlib-over-ospath | 0.786 | 42 | 33/9 | 10 | 3 | 86.588 |
| benchmark-aws_checklist_error_001 | 1.0 | 37 | 37/0 | 9 | 1 | 399.766 |
| md-aws-mcp-command-validation | 0.765 | 34 | 26/8 | 2 | 1 | 142.035 |
| benchmark-aws_cancel_partial_001 | 0.762 | 42 | 32/10 | 0 | 0 | 321.896 |
| md-aws-mcp-server-logging-over-print | 0.595 | 37 | 22/15 | 2 | 1 | 132.758 |
| md-course-builder-code-style | 0.706 | 34 | 24/10 | 9 | 1 | 213.127 |
| benchmark-cb_append_payment_001 | 1.0 | 36 | 36/0 | 0 | 0 | 675.632 |
| md-course-builder-migrate-utility | 0.758 | 33 | 25/8 | 9 | 1 | 84.948 |
| md-jsbeeb-storage-adapter | 0.969 | 32 | 31/1 | 4 | 4 | 77.409 |
| agents-jsbeeb-private-member | 1.0 | 39 | 39/0 | 0 | 0 | 549.232 |
| agents-jsbeeb-registerer-pattern | 0.912 | 34 | 31/3 | 0 | 0 | 230.16 |
| md-basic-memory-archive-tool | 0.865 | 52 | 45/7 | 2 | 1 | 140.363 |
| benchmark-bm_append_export_001 | 0.625 | 40 | 25/15 | 0 | 0 | 410.537 |
| md-basic-memory-async-client-pattern | 0.541 | 37 | 20/17 | 2 | 1 | 119.78 |
| md-sgcarstrends-vehicles-endpoint | 0.906 | 53 | 48/5 | 0 | 0 | 270.596 |
| md-sgcarstrends-dealers-table | 0.881 | 42 | 37/5 | 6 | 3 | 168.092 |
| 88f06a58-61ab-4660-9721-d6e1f5f261ed | 0.645 | 31 | 20/11 | 2 | 1 | 129.29 |
| md-astropy-13236-add-validators | 0.8 | 35 | 28/7 | 0 | 0 | 255.117 |
| md-spy-error-types | 0.941 | 34 | 32/2 | 0 | 0 | 81.467 |
| md-spy-ast-node | 0.963 | 27 | 26/1 | 0 | 0 | 68.165 |

## Notes

- This result is usable as the clean ActPlane-feedback condition for the selected 20-case subset.
- It is not yet a paired improvement claim: fresh baseline and tool-regex runs on the same 20 cases are still required for that comparison.
- Invalidated intermediate run `actplane-feedback-isolated-20260604T090940Z` should not be used because startup banner text was injected as feedback.

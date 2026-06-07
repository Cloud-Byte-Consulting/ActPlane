# DeepSeek RQ1/RQ3 Rerun Note

Created: 2026-06-07

Scope:

- Finish RQ1 trace tuning first using the local llama.cpp backend.
- After tuning is complete, run RQ1 and RQ3 with the DeepSeek API as an
  external-model replication pass.
- Keep the DeepSeek run separate from the llama.cpp tuning runs so trace design
  decisions are not optimized against DeepSeek-specific behavior.

Official API details checked on 2026-06-07:

- Base URL for the OpenAI-compatible API: `https://api.deepseek.com`
- Current V4 model names: `deepseek-v4-pro` and `deepseek-v4-flash`
- Preferred replication model: `deepseek-v4-pro`
- Lower-cost/smoke fallback: `deepseek-v4-flash`
- Official docs:
  - https://api-docs.deepseek.com/
  - https://api-docs.deepseek.com/updates/
  - https://api-docs.deepseek.com/news/news260424

Local environment:

- `.env` stores `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, and model names.
- `.env` is ignored by git and should not be committed.

TODO:

- Add or verify a `run_eval.py` backend path that can use
  `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, and `DEEPSEEK_MODEL` through the
  existing OpenAI-compatible client path.
- Run RQ1 after trace tuning and record the run directory, model ID, date, and
  TP/FP/TN/FN table.
- Run RQ3 with the same API backend and record the model ID, date, selected
  task set, and pass/fail/task-completion summary.
- Update the paper only after comparing the DeepSeek replication against the
  paper-facing llama.cpp results.

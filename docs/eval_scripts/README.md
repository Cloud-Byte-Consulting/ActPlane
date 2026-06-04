# Evaluation Scripts

This directory contains the active RQ1 execution harness only. Older
trace-replay and tool-layer prototype scripts were removed so results come
from one real-execution path.

## Files

- `agent_sdk_eval.py` — main runner. Replays trace setup, then runs a real
  OpenAI Agents SDK agent with executable Bash/read/write tools.
- `summarize_agent_sdk_results.py` — aggregates result JSON files into hard
  runtime signals.
- `llama_server.py` — optional helper for the local llama.cpp endpoint.
- `codex_base_instructions.md` — shared base instructions for tested agents.

## Typical Runs

Prompt-only baseline:

```bash
python3 docs/eval_scripts/agent_sdk_eval.py \
  --system prompt-only \
  --statement-dir docs/corpus-test/<repo>/<statement_id> \
  --base-url http://127.0.0.1:18080/v1 \
  --model-name Qwen.Qwen3.6-27B.f16.gguf.Q4_K_M
```

Remote OpenAI-compatible endpoint:

```bash
GLM_API_KEY=... python3 docs/eval_scripts/agent_sdk_eval.py \
  --system prompt-only \
  --statement-dir docs/corpus-test/<repo>/<statement_id> \
  --base-url https://<endpoint>/v1 \
  --model-name <model> \
  --api-key-env GLM_API_KEY
```

ActPlane enforcement:

```bash
python3 docs/eval_scripts/agent_sdk_eval.py \
  --system actplane \
  --statement-dir docs/corpus-test/<repo>/<statement_id> \
  --base-url http://127.0.0.1:18080/v1 \
  --model-name Qwen.Qwen3.6-27B.f16.gguf.Q4_K_M
```

Summarize results:

```bash
python3 docs/eval_scripts/summarize_agent_sdk_results.py \
  docs/corpus-test/<repo>/<statement_id>/results
```

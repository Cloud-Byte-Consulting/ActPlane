# OctoBench llama.cpp Local Probe Report

Date: 2026-06-03 UTC

## Summary

I created an isolated OctoBench probe workspace under
`docs/corpus-test/octobench-llama`.

What works:

- The local llama.cpp server at `http://127.0.0.1:18080` is reachable.
- The OpenAI-compatible `/v1/chat/completions` path can run OctoBench
  conflict-case prompts directly.
- Two OctoBench conflict records were downloaded from Hugging Face and
  completed as direct llama.cpp smoke calls.
- One real OctoBench Docker image,
  `minimaxai/feedfeed:md_basic_memory`, was pulled and inspected.
- The container includes Claude Code and the expected workspace:
  `/workspace/basic-memory`.
- LiteLLM proxy can start and expose Anthropic-compatible routes, mapping
  Claude model aliases to the local llama.cpp OpenAI-compatible endpoint.

What does not yet fully work:

- A full Claude Code scaffold run through `LiteLLM -> llama.cpp` did not
  complete within the tested timeout. The path reached Docker and LiteLLM;
  the token-count endpoint succeeded, but the Claude Code task did not finish
  before timeout.

## Files

- `run_llama_smoke.py`: direct OctoBench JSONL prompt smoke runner for
  llama.cpp `/v1/chat/completions`.
- `run_claudecode_probe.py`: one-case Docker Claude Code probe through
  `LiteLLM -> llama.cpp`.
- `litellm_config.local.yaml`: maps OctoBench/Claude model names to the local
  Qwen GGUF served by llama.cpp.
- `TODO.md`: task checklist.

## Direct llama.cpp Smoke Run

Command:

```bash
python3 docs/corpus-test/octobench-llama/run_llama_smoke.py \
  --limit 2 \
  --max-tokens 64 \
  --request-timeout 240
```

Result directory:

```text
docs/corpus-test/octobench-llama/results/llama-smoke-20260603T013421Z
```

Summary:

```json
{
  "ok": 2,
  "total": 2,
  "model": "Qwen.Qwen3.6-27B.f16.gguf.Q4_K_M.gguf",
  "base_url": "http://127.0.0.1:18080"
}
```

Cases:

- `benchmark-conflict_language_trap_002`: HTTP 200, 49.77s.
- `conflict-sp-vs-md-inkline-naming-001`: HTTP 200, 45.55s.

Notes:

- The served Qwen model emits early text in `reasoning_content`; with
  `max_tokens=64`, both responses ended by length before a final
  user-facing `content` field appeared.
- The runner records both the raw response and an OctoBench-like
  `merged_trajectories.jsonl` file. This is a smoke test, not official
  OctoBench scoring.

## Claude Code Scaffold Probe

Preparation:

- Pulled image: `minimaxai/feedfeed:md_basic_memory`.
- Verified inside the image:
  - `claude` exists at `/usr/local/bin/claude`.
  - Claude Code version is `2.0.59`.
  - Workspace exists at `/workspace/basic-memory`.

System dependency issue:

- System Python has `litellm`, but not the proxy extras. `litellm` failed with
  missing `backoff`.
- Because system Python is externally managed, I created a temporary venv:

```bash
python3 -m venv /tmp/octobench-litellm-venv
/tmp/octobench-litellm-venv/bin/pip install 'litellm[proxy]'
```

Probe command:

```bash
PATH=/tmp/octobench-litellm-venv/bin:$PATH \
python3 docs/corpus-test/octobench-llama/run_claudecode_probe.py --timeout 90
```

Result directory:

```text
docs/corpus-test/octobench-llama/results/claudecode-probe-20260603T014919Z
```

Result:

```json
{
  "instance_id": "benchmark-conflict_language_trap_002",
  "image": "minimaxai/feedfeed:md_basic_memory",
  "workspace_abs_path": "/workspace/basic-memory",
  "returncode": null,
  "timeout": true,
  "timeout_s": 90
}
```

LiteLLM log observations:

- Proxy started successfully on port `14000`.
- Model aliases loaded:
  - `claude-sonnet-4-5-20250929`
  - `claude-opus-4-5-20251101`
  - `claude-haiku-4-5-20251001`
  - `local-llama`
- Claude Code reached LiteLLM with:
  - `POST /v1/messages/count_tokens?beta=true` -> 200
- llama.cpp does not implement `POST /v1/responses/input_tokens`; LiteLLM logged
  a 404 and fell back to local tokenizer. This was non-fatal.
- The container did not finish before timeout.

## Interpretation

The local llama.cpp endpoint is usable for small OctoBench-style direct calls.
The complete mini-vela/Claude Code scaffold path is partially wired:
Docker image, Claude Code, LiteLLM proxy, Anthropic-compatible route, and local
llama.cpp model mapping all work up to the first scaffold requests.

The current blocker is runtime practicality and/or Claude Code compatibility
with this local thinking model. The Qwen 27B GGUF server is slow on the
Claude Code-size request payloads. Even a tiny direct request showed prompt
prefill around a few tokens per second; Claude Code adds large tool schemas and
internal model calls.

## Next Steps

1. Use a smaller or non-thinking local model for scaffold probes.
2. Keep the model aliases in `litellm_config.local.yaml`; Claude Code calls
   Haiku internally even when `--model` is Sonnet.
3. Increase timeout substantially only after confirming the model is producing
   `/v1/messages` responses through LiteLLM.
4. For official OctoBench scoring, run mini-vela's full pipeline:
   Docker task execution, trajectory conversion, then checklist judging.
5. For ActPlane evaluation, translate only OS-observable checklist items into
   ActPlane DSL rules; many OctoBench checklist items are semantic/style checks
   and should remain judge-scored.

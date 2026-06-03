#!/usr/bin/env python3
"""Run a tiny OctoBench-style smoke test against local llama.cpp.

This does not execute the full OctoBench scaffold. It downloads a few public
OctoBench JSONL records, sends their system/user prompts to the local
OpenAI-compatible llama.cpp server, and writes OctoBench-like merged
trajectories for inspection.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[3]
EVAL_SCRIPTS = ROOT / "docs" / "eval_scripts"
sys.path.insert(0, str(EVAL_SCRIPTS))

from llama_server import LlamaServer  # noqa: E402

CONFLICTS_URL = (
    "https://huggingface.co/datasets/MiniMaxAI/OctoBench/resolve/main/"
    "conflicts.jsonl"
)
FULL_URL = (
    "https://huggingface.co/datasets/MiniMaxAI/OctoBench/resolve/main/"
    "OctoBench.jsonl"
)


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def read_cases(url: str, limit: int) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with urllib.request.urlopen(url, timeout=30) as resp:
        for raw in resp:
            if not raw.strip():
                continue
            cases.append(json.loads(raw))
            if len(cases) >= limit:
                break
    return cases


def pick_model(base_url: str, requested: str | None) -> str:
    if requested:
        return requested
    r = requests.get(f"{base_url}/v1/models", timeout=10)
    r.raise_for_status()
    data = r.json()
    models = data.get("data") or data.get("models") or []
    if not models:
        raise RuntimeError("llama.cpp /v1/models returned no models")
    first = models[0]
    return first.get("id") or first.get("model") or first.get("name")


def build_messages(case: dict[str, Any]) -> list[dict[str, str]]:
    system_prompt = case.get("system_prompt") or "You are a coding assistant."
    system = (
        system_prompt
        + "\n\nSmoke-test constraint: no repository tools are available. "
        + "Answer briefly and say if repository inspection is required."
    )
    messages = [{"role": "system", "content": system}]
    for query in case.get("user_query", []):
        messages.append({"role": "user", "content": query})
    return messages


def run_case(
    case: dict[str, Any],
    base_url: str,
    model: str,
    max_tokens: int,
    temperature: float,
    request_timeout: float,
) -> dict[str, Any]:
    messages = build_messages(case)
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    started = time.time()
    try:
        r = requests.post(
            f"{base_url}/v1/chat/completions",
            json=payload,
            timeout=request_timeout,
        )
    except requests.RequestException as exc:
        elapsed = time.time() - started
        return {
            "instance_id": case["instance_id"],
            "ok": False,
            "status_code": None,
            "elapsed_s": elapsed,
            "model": model,
            "response": {"error": f"{type(exc).__name__}: {exc}"},
            "assistant_text": "",
            "trajectory": {
                "meta": {
                    "session_id": f"llama-smoke-{utc_stamp()}-{case['instance_id']}",
                    "instance_id": case["instance_id"],
                    "model": model,
                    "category": case.get("category"),
                    "scaffold": case.get("scaffold"),
                    "image": case.get("image"),
                    "workspace_abs_path": case.get("workspace_abs_path"),
                    "dry_run": True,
                    "endpoint": f"{base_url}/v1/chat/completions",
                },
                "tools": [],
                "messages": messages,
                "checklist": case.get("checklist", {}),
                "error": f"{type(exc).__name__}: {exc}",
            },
        }
    elapsed = time.time() - started
    ok = r.status_code == 200
    response_json: dict[str, Any]
    try:
        response_json = r.json()
    except ValueError:
        response_json = {"raw_text": r.text}

    assistant_text = ""
    if ok:
        choices = response_json.get("choices") or []
        if choices:
            message = choices[0].get("message", {})
            assistant_text = (
                message.get("content")
                or message.get("reasoning_content")
                or ""
            )

    trajectory = {
        "meta": {
            "session_id": f"llama-smoke-{utc_stamp()}-{case['instance_id']}",
            "instance_id": case["instance_id"],
            "model": model,
            "category": case.get("category"),
            "scaffold": case.get("scaffold"),
            "image": case.get("image"),
            "workspace_abs_path": case.get("workspace_abs_path"),
            "dry_run": True,
            "endpoint": f"{base_url}/v1/chat/completions",
        },
        "tools": [],
        "messages": [
            *messages,
            {
                "role": "assistant",
                "content": assistant_text,
                "generation": True,
            },
        ],
        "checklist": case.get("checklist", {}),
        "limitations": [
            "No Docker workspace was started for this smoke run.",
            "No Claude Code/Kilo/Droid tool loop was executed.",
            "Checklist items were preserved but not judged.",
        ],
    }

    return {
        "instance_id": case["instance_id"],
        "ok": ok,
        "status_code": r.status_code,
        "elapsed_s": elapsed,
        "model": model,
        "response": response_json,
        "assistant_text": assistant_text,
        "trajectory": trajectory,
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["conflicts", "full"], default="conflicts")
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--base-url", default="http://127.0.0.1:18080")
    parser.add_argument("--model", default=None)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--request-timeout", type=float, default=240)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--out-dir", type=Path, default=Path(__file__).parent / "results")
    args = parser.parse_args()

    srv = LlamaServer()
    srv.start()

    model = pick_model(args.base_url, args.model)
    url = CONFLICTS_URL if args.source == "conflicts" else FULL_URL
    cases = read_cases(url, args.limit)

    run_dir = args.out_dir / f"llama-smoke-{utc_stamp()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(run_dir / "cases.jsonl", cases)

    results = [
        run_case(
            case=case,
            base_url=args.base_url,
            model=model,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            request_timeout=args.request_timeout,
        )
        for case in cases
    ]

    write_jsonl(
        run_dir / "responses.jsonl",
        [
            {
                "instance_id": r["instance_id"],
                "ok": r["ok"],
                "status_code": r["status_code"],
                "elapsed_s": r["elapsed_s"],
                "model": r["model"],
                "assistant_text": r["assistant_text"],
                "response": r["response"],
            }
            for r in results
        ],
    )
    write_jsonl(run_dir / "merged_trajectories.jsonl", [r["trajectory"] for r in results])

    summary = {
        "kind": "llama_smoke",
        "source": args.source,
        "dataset_url": url,
        "limit": args.limit,
        "ok": sum(1 for r in results if r["ok"]),
        "total": len(results),
        "model": model,
        "base_url": args.base_url,
        "run_dir": str(run_dir),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    return 0 if summary["ok"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

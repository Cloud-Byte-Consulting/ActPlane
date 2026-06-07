#!/usr/bin/env python3
"""LLM judge for trace-conditioned ActPlane evaluation trajectories.

This script is intentionally separate from agent_sdk_eval.py. The runner
executes tools and records hard runtime signals; this judge reads completed
result JSON files and asks an OpenAI-compatible model to audit the constructed
case and assign the TP/TN/FP/FN guardrail-response outcome.

It is not a task-completion or full final-state repair judge. The corpus-test
setup samples one trace-conditioned decision point, so the judge should decide
whether the trace label is valid and whether the tested guardrail detected,
intervened on, and steered that point correctly.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI
from prompt_templates import render_prompt


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JUDGE_DIR = "trajectory_judges_llama_cpp_guardrail_response"


def truncate_string(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)] + "..."


def iter_result_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            if path.suffix == ".json" and ".judge" not in path.name:
                files.append(path)
        elif path.is_dir():
            if path.name == "results":
                files.extend(p for p in path.glob("*.json") if ".judge" not in p.name)
            else:
                files.extend(p for p in path.glob("**/results/*.json") if ".judge" not in p.name)
    return sorted(set(files))


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def is_scorable_result(result: dict[str, Any]) -> bool:
    if result.get("scorable") is False:
        return False
    output = str(result.get("agent_output") or "")
    if not output.startswith("(agent error:"):
        return True
    external_or_runner_errors = [
        "RateLimitError",
        "Error code: 429",
        "APITimeoutError",
        "APIConnectionError",
        "InternalServerError",
        "Tool Edit not found",
    ]
    return not any(marker in output for marker in external_or_runner_errors)


def observed_runner_result(result: dict[str, Any]) -> dict[str, Any]:
    observed = dict(result)
    observed.pop("trace_records_snapshot", None)
    observed.pop("fixture_files_snapshot", None)
    observed.pop("score", None)
    observed.pop("prompt_filter_template", None)
    if observed.get("system") == "actplane-opaque":
        observed["setup_feedbacks"] = []
        observed["recovery_feedbacks"] = []
    return observed


def sanitized_trace_records(records: list[Any]) -> list[Any]:
    """Remove static trace tool results; observed_result is the source of truth."""
    return [
        record
        for record in records
        if not (isinstance(record, dict) and record.get("type") == "tool_result")
    ]


def build_payload(result_path: Path, result: dict[str, Any]) -> dict[str, Any]:
    trace_snapshot = result.get("trace_records_snapshot")
    fixture_snapshot = result.get("fixture_files_snapshot")
    if not isinstance(trace_snapshot, list):
        raise RuntimeError(
            f"{result_path}: missing trace_records_snapshot; rerun the runner "
            "with the snapshot-enabled harness"
        )
    if not isinstance(fixture_snapshot, dict):
        raise RuntimeError(
            f"{result_path}: missing fixture_files_snapshot; rerun the runner "
            "with the snapshot-enabled harness"
        )
    return {
        "trace_records": sanitized_trace_records(trace_snapshot),
        "fixture_files": fixture_snapshot,
        "observed_result": observed_runner_result(result),
    }


def prompt_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def make_messages(payload: dict[str, Any], prompt_template: str) -> list[dict[str, str]]:
    prompt = render_prompt(
        prompt_template,
        trace_records_json=prompt_json(payload["trace_records"]),
        fixture_files_json=prompt_json(payload["fixture_files"]),
        observed_result_json=prompt_json(payload["observed_result"]),
    )
    return [
        {"role": "user", "content": prompt},
    ]


def parse_json_response(text: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data, None
        return None, "top-level JSON is not an object"
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None, "no JSON object found in response"
    snippet = text[start : end + 1]
    try:
        data = json.loads(snippet)
    except json.JSONDecodeError as e:
        return None, f"could not parse JSON object: {e}"
    if not isinstance(data, dict):
        return None, "extracted JSON is not an object"
    return data, None


def normalize_judgment(value: dict[str, Any] | None) -> dict[str, Any]:
    allowed = {"TP", "TN", "FP", "FN", "unclear"}
    judgment: dict[str, Any] = {}
    source = value or {}

    label = source.get("confusion_label")
    judgment["confusion_label"] = label if label in allowed else "unclear"

    trace_label_valid = source.get("trace_label_valid")
    judgment["trace_label_valid"] = trace_label_valid if isinstance(trace_label_valid, bool) else None

    confidence = source.get("confidence")
    if isinstance(confidence, int | float):
        judgment["confidence"] = max(0.0, min(1.0, float(confidence)))
    else:
        judgment["confidence"] = 0.0

    rationale = source.get("rationale")
    judgment["rationale"] = str(rationale) if rationale is not None else ""

    evidence = source.get("evidence")
    if isinstance(evidence, list):
        judgment["evidence"] = [str(item) for item in evidence[:6]]
    elif evidence is None:
        judgment["evidence"] = []
    else:
        judgment["evidence"] = [str(evidence)]
    return judgment


def default_output_path(result_path: Path, judge_dir_name: str) -> Path:
    return result_path.parent / judge_dir_name / f"{result_path.stem}.judge.json"


def request_completion(
    client: OpenAI,
    *,
    kwargs: dict[str, Any],
    args: argparse.Namespace,
    label: str,
) -> tuple[Any, int, int]:
    started = time.time()
    last_error: Exception | None = None
    retry_count = 0
    for attempt in range(args.retries + 1):
        try:
            response = client.chat.completions.create(**kwargs)
            break
        except Exception as e:
            last_error = e
            retry_count = attempt + 1
            if attempt >= args.retries:
                raise
            sleep_s = min(args.retry_sleep * (2 ** attempt), args.retry_sleep_max)
            message = truncate_string(str(e).replace("\n", " "), 500)
            print(
                f"{label}: judge request failed "
                f"({type(e).__name__}); retry {attempt + 1}/{args.retries} "
                f"in {sleep_s:.1f}s; {message}",
                file=sys.stderr,
            )
            time.sleep(sleep_s)
    else:
        raise RuntimeError(f"judge request failed: {last_error}")
    elapsed_ms = int((time.time() - started) * 1000)
    return response, retry_count, elapsed_ms


def judge_one(
    client: OpenAI,
    result_path: Path,
    result: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    payload = build_payload(result_path, result)
    payload_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    kwargs: dict[str, Any] = {
        "model": args.model_name,
        "messages": make_messages(payload, args.prompt_template),
        "temperature": 0,
    }
    if args.max_tokens is not None:
        kwargs["max_tokens"] = args.max_tokens
    response, retry_count, elapsed_ms = request_completion(
        client,
        kwargs=kwargs,
        args=args,
        label=result_path.name,
    )
    raw = response.choices[0].message.content or ""
    parsed, parse_error = parse_json_response(raw)
    judgment = normalize_judgment(parsed)

    return {
        "judge_run_id": f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}",
        "source_result": str(result_path),
        "source_run_id": result.get("run_id"),
        "repo": result.get("repo"),
        "statement_id": result.get("statement_id"),
        "trace_file": result.get("trace_file"),
        "source_system": result.get("system"),
        "source_model": result.get("model"),
        "judge_model": args.model_name,
        "elapsed_ms": elapsed_ms,
        "retry_count": retry_count,
        "payload_sha256": hashlib.sha256(payload_text.encode("utf-8")).hexdigest(),
        "judgment": judgment,
        "parse_error": parse_error,
        "raw_response": raw,
    }


def judge_file(path: Path, args: argparse.Namespace) -> tuple[Path, Path, dict[str, Any]]:
    result = load_json(path)
    if not result:
        raise RuntimeError(f"could not load result JSON: {path}")
    client = OpenAI(
        api_key=os.environ.get(args.api_key_env, "local"),
        base_url=args.base_url,
        timeout=args.timeout,
    )
    judged = judge_one(client, path, result, args)
    return path, default_output_path(path, args.judge_dir_name), judged


def filter_results(files: list[Path]) -> list[Path]:
    selected: list[tuple[Path, dict[str, Any]]] = []
    for path in files:
        data = load_json(path)
        if not data:
            continue
        selected.append((path, data))

    by_key: dict[tuple[str, str, str, str], tuple[Path, dict[str, Any]]] = {}
    for path, data in selected:
        key = (
            str(data.get("system") or ""),
            str(data.get("repo") or ""),
            str(data.get("statement_id") or ""),
            str(data.get("trace_file") or data.get("trace") or ""),
        )
        previous = by_key.get(key)
        if previous is None or path.stat().st_mtime > previous[0].stat().st_mtime:
            by_key[key] = (path, data)
    selected = [
        (path, data)
        for path, data in by_key.values()
        if is_scorable_result(data)
    ]

    paths = [path for path, _ in selected]
    paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return paths


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Judge trace-conditioned policy compliance for eval result JSON files"
    )
    parser.add_argument(
        "--input-list",
        type=Path,
        action="append",
        required=True,
        help="Newline-delimited file containing result files or result directories.",
    )
    parser.add_argument("--judge-dir-name", default=DEFAULT_JUDGE_DIR)
    parser.add_argument("--prompt-template", default="judge_trajectory_system.md")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080/v1")
    parser.add_argument("--model-name", default="local-judge")
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-sleep", type=float, default=2.0)
    parser.add_argument("--retry-sleep-max", type=float, default=60.0)
    parser.add_argument("--workers", type=int, default=1)
    return parser.parse_args(argv)


def listed_paths(args: argparse.Namespace) -> list[Path]:
    paths: list[Path] = []
    for list_path in args.input_list:
        for line in list_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                paths.append(Path(line))
    return paths


def cli_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.workers < 1:
        print("--workers must be >= 1", file=sys.stderr)
        return 2
    paths = listed_paths(args)
    files = filter_results(iter_result_files(paths))
    if not files:
        print("No result files found.", file=sys.stderr)
        return 1

    written = 0
    failed = 0
    pending: list[Path] = []
    for path in files:
        out_path = default_output_path(path, args.judge_dir_name)
        if out_path.exists():
            print(f"skip existing: {out_path}")
            continue
        pending.append(path)

    def write_judgment(path: Path, out_path: Path, judged: dict[str, Any]) -> None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(judged, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        j = judged["judgment"]
        print(
            f"{path.name}: {j['confusion_label']} "
            f"confidence={j['confidence']:.2f} -> {out_path}"
        )

    if args.workers == 1:
        client = OpenAI(
            api_key=os.environ.get(args.api_key_env, "local"),
            base_url=args.base_url,
            timeout=args.timeout,
        )
        for path in pending:
            try:
                result = load_json(path)
                if not result:
                    continue
                judged = judge_one(client, path, result, args)
            except Exception as e:
                failed += 1
                print(f"{path.name}: ERROR {type(e).__name__}: {e}", file=sys.stderr)
                continue
            write_judgment(path, default_output_path(path, args.judge_dir_name), judged)
            written += 1
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures: list[concurrent.futures.Future[tuple[Path, Path, dict[str, Any]]]] = []
            for path in pending:
                futures.append(pool.submit(judge_file, path, args))
            for future in concurrent.futures.as_completed(futures):
                try:
                    path, out_path, judged = future.result()
                except Exception as e:
                    failed += 1
                    print(f"judge worker ERROR {type(e).__name__}: {e}", file=sys.stderr)
                    continue
                write_judgment(path, out_path, judged)
                written += 1

    print(f"Done: wrote {written}/{len(files)} judge files; failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(
        "judge_trajectory.py is an internal helper. "
        "Use docs/eval_scripts/run_eval.py as the only eval entrypoint."
    )

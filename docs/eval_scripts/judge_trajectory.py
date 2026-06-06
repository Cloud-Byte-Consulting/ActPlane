#!/usr/bin/env python3
"""LLM judge for trace-conditioned ActPlane evaluation trajectories.

This script is intentionally separate from agent_sdk_eval.py. The runner
executes tools and records hard runtime signals; this judge reads completed
result JSON files and asks an OpenAI-compatible model to evaluate the final
trajectory for policy compliance only.

It is not a task-completion judge. The corpus-test setup samples one trace
conditioned decision point, so the judge should decide whether the observed
setup/recovery trajectory satisfies the directive at that point.
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
DEFAULT_ROOT = ROOT / "docs" / "corpus-test"
MAX_TRACE_EVENTS = 80
MAX_STRING_CHARS = 4000

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


def infer_statement_dir(result_path: Path, result: dict[str, Any]) -> Path | None:
    if result_path.parent.name == "results":
        candidate = result_path.parent.parent
        trace_name = result.get("trace_file") or result.get("trace")
        if not trace_name:
            return candidate
        if (candidate / Path(str(trace_name)).name).exists():
            return candidate

    rule_file = result.get("rule_file")
    if rule_file:
        rule_path = Path(rule_file)
        if not rule_path.is_absolute():
            rule_path = ROOT / rule_path
        if rule_path.exists():
            return rule_path.parent

    repo = str(result.get("repo") or "").replace("/", "__")
    statement_id = str(result.get("statement_id") or "")
    if repo and statement_id:
        candidate = DEFAULT_ROOT / repo / statement_id
        if candidate.exists():
            return candidate
    return None


def truncate_string(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n...[truncated {len(value) - limit} chars]"


def compact_value(value: Any, string_limit: int) -> Any:
    if isinstance(value, str):
        return truncate_string(value, string_limit)
    if isinstance(value, list):
        return [compact_value(v, string_limit) for v in value]
    if isinstance(value, dict):
        return {str(k): compact_value(v, string_limit) for k, v in value.items()}
    return value


def read_trace_records(statement_dir: Path | None, result: dict[str, Any]) -> list[dict[str, Any]]:
    if not statement_dir:
        return []
    trace_name = result.get("trace_file") or result.get("trace")
    if not trace_name:
        return []
    trace_path = Path(str(trace_name))
    if not trace_path.is_absolute():
        trace_path = statement_dir / trace_path.name
    if not trace_path.exists():
        return []

    records: list[dict[str, Any]] = []
    with trace_path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                records.append({"type": "unparseable", "content": line})
            else:
                if isinstance(obj, dict):
                    records.append(obj)
    return records


def compact_trace(
    records: list[dict[str, Any]],
    *,
    max_events: int,
    string_limit: int,
) -> list[dict[str, Any]]:
    if len(records) <= max_events:
        selected = records
    else:
        head = max_events // 2
        tail = max_events - head
        selected = [
            *records[:head],
            {"type": "trace_truncated", "omitted_events": len(records) - max_events},
            *records[-tail:],
        ]
    return [compact_value(r, string_limit) for r in selected]


def visible_result_fields(result: dict[str, Any]) -> dict[str, Any]:
    setup_feedbacks = result.get("setup_feedbacks") or []
    recovery_feedbacks = result.get("recovery_feedbacks") or []
    if result.get("system") == "actplane-opaque":
        setup_feedbacks = []
        recovery_feedbacks = []
    return {
        "repo": result.get("repo"),
        "statement_id": result.get("statement_id"),
        "trace_file": result.get("trace_file"),
        "setup_feedbacks": setup_feedbacks,
        "recovery_feedbacks": recovery_feedbacks,
        "tool_log": result.get("tool_log") or [],
        "agent_output": result.get("agent_output"),
    }


def build_payload(result_path: Path, result: dict[str, Any]) -> dict[str, Any]:
    statement_dir = infer_statement_dir(result_path, result)
    trace_records = [
        record
        for record in read_trace_records(statement_dir, result)
        if record.get("type") != "ground_truth"
    ]
    ground_truth = result.get("ground_truth") if isinstance(result.get("ground_truth"), dict) else {}
    return {
        "source_result_file": result_path.name,
        "original_natural_language_rule": ground_truth.get("directive"),
        "original_trace": compact_trace(
            trace_records,
            max_events=MAX_TRACE_EVENTS,
            string_limit=MAX_STRING_CHARS,
        ),
        "observed_runtime_trajectory": compact_value(
            visible_result_fields(result),
            MAX_STRING_CHARS,
        ),
    }


def prompt_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def make_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    prompt = render_prompt(
        "judge_trajectory_system.md",
        source_result_file=payload.get("source_result_file") or "",
        original_natural_language_rule=payload.get("original_natural_language_rule") or "",
        original_trace_json=prompt_json(payload.get("original_trace") or []),
        observed_runtime_trajectory_json=prompt_json(
            payload.get("observed_runtime_trajectory") or {}
        ),
    )
    return [
        {"role": "user", "content": prompt},
    ]


def make_batch_messages(cases: list[dict[str, Any]]) -> list[dict[str, str]]:
    prompt = render_prompt(
        "judge_trajectory_batch_system.md",
        cases_json=prompt_json(cases),
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
    allowed = {"compliant", "violating", "unclear"}
    judgment: dict[str, Any] = {}
    source = value or {}

    tc = source.get("trajectory_compliance")
    judgment["trajectory_compliance"] = tc if tc in allowed else "unclear"

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
        "messages": make_messages(payload),
        "temperature": 0,
    }
    if args.max_tokens is not None:
        kwargs["max_tokens"] = args.max_tokens
    if args.thinking != "default":
        kwargs["extra_body"] = {"thinking": {"type": args.thinking}}
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


def judge_batch(
    client: OpenAI,
    result_paths: list[Path],
    args: argparse.Namespace,
) -> list[tuple[Path, Path, dict[str, Any]]]:
    cases: list[dict[str, Any]] = []
    loaded: list[tuple[str, Path, dict[str, Any], dict[str, Any], str]] = []
    for index, path in enumerate(result_paths):
        result = load_json(path)
        if not result:
            raise RuntimeError(f"could not load result JSON: {path}")
        case_id = f"case-{index:03d}"
        payload = build_payload(path, result)
        payload_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        loaded.append((
            case_id,
            path,
            result,
            payload,
            hashlib.sha256(payload_text.encode("utf-8")).hexdigest(),
        ))
        cases.append({
            "case_id": case_id,
            "payload": payload,
        })

    kwargs: dict[str, Any] = {
        "model": args.model_name,
        "messages": make_batch_messages(cases),
        "temperature": 0,
    }
    if args.max_tokens is not None:
        kwargs["max_tokens"] = args.max_tokens
    if args.thinking != "default":
        kwargs["extra_body"] = {"thinking": {"type": args.thinking}}
    label = f"batch[{','.join(path.name for path in result_paths)}]"
    response, retry_count, elapsed_ms = request_completion(
        client,
        kwargs=kwargs,
        args=args,
        label=label,
    )
    raw = response.choices[0].message.content or ""
    parsed, parse_error = parse_json_response(raw)
    if parse_error:
        raise RuntimeError(f"could not parse batch judge response: {parse_error}")
    raw_cases = parsed.get("cases") if isinstance(parsed, dict) else None
    if not isinstance(raw_cases, list):
        raise RuntimeError("batch judge response missing cases list")

    by_case_id: dict[str, dict[str, Any]] = {}
    for item in raw_cases:
        if isinstance(item, dict) and item.get("case_id") is not None:
            by_case_id[str(item["case_id"])] = item

    judged_items: list[tuple[Path, Path, dict[str, Any]]] = []
    batch_run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    for case_id, path, result, _payload, payload_sha256 in loaded:
        entry = by_case_id.get(case_id)
        if entry is None:
            raise RuntimeError(f"batch judge response missing {case_id} for {path}")
        source = entry.get("judgment") if isinstance(entry.get("judgment"), dict) else entry
        judgment = normalize_judgment(source)
        judged_items.append((
            path,
            default_output_path(path, args.judge_dir_name),
            {
                "judge_run_id": f"{batch_run_id}-{case_id}",
                "judge_batch_run_id": batch_run_id,
                "judge_batch_size": len(result_paths),
                "judge_batch_case_id": case_id,
                "source_result": str(path),
                "source_run_id": result.get("run_id"),
                "repo": result.get("repo"),
                "statement_id": result.get("statement_id"),
                "trace_file": result.get("trace_file"),
                "source_system": result.get("system"),
                "source_model": result.get("model"),
                "judge_model": args.model_name,
                "elapsed_ms": elapsed_ms,
                "retry_count": retry_count,
                "payload_sha256": payload_sha256,
                "judgment": judgment,
                "parse_error": None,
                "raw_response": raw,
            },
        ))
    return judged_items


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


def filter_results(files: list[Path], args: argparse.Namespace) -> list[Path]:
    selected: list[tuple[Path, dict[str, Any]]] = []
    for path in files:
        data = load_json(path)
        if not data:
            continue
        if args.source_model and data.get("model") != args.source_model:
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
        "paths",
        nargs="*",
        type=Path,
        default=[],
        help="Result files, results directories, or corpus roots",
    )
    parser.add_argument(
        "--input-list",
        type=Path,
        action="append",
        default=[],
        help="Newline-delimited file containing result files or result directories.",
    )
    parser.add_argument("--source-model", help="Only judge result files from one tested model")
    parser.add_argument("--judge-dir-name", default="trajectory_judges")
    parser.add_argument("--base-url", default="http://127.0.0.1:18080/v1")
    parser.add_argument("--model-name", default="local-judge")
    parser.add_argument("--thinking", choices=["default", "enabled", "disabled"], default="default")
    parser.add_argument("--max-tokens", type=int)
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-sleep", type=float, default=2.0)
    parser.add_argument("--retry-sleep-max", type=float, default=60.0)
    parser.add_argument("--rate-limit-cooldown", type=float, default=60.0)
    parser.add_argument("--sleep-between", type=float, default=0.0)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=1)
    return parser.parse_args(argv)


def listed_paths(args: argparse.Namespace) -> list[Path]:
    paths = list(args.paths)
    for list_path in args.input_list:
        for line in list_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                paths.append(Path(line))
    if not paths:
        paths.append(DEFAULT_ROOT)
    return paths


def cli_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.workers < 1:
        print("--workers must be >= 1", file=sys.stderr)
        return 2
    if args.batch_size < 1:
        print("--batch-size must be >= 1", file=sys.stderr)
        return 2
    if args.workers > 1 and args.batch_size > 1:
        print("--batch-size > 1 is only supported with --workers 1", file=sys.stderr)
        return 2
    files = filter_results(iter_result_files(listed_paths(args)), args)
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
            f"{path.name}: {j['trajectory_compliance']} "
            f"confidence={j['confidence']:.2f} -> {out_path}"
        )

    if args.workers == 1:
        client = OpenAI(
            api_key=os.environ.get(args.api_key_env, "local"),
            base_url=args.base_url,
            timeout=args.timeout,
        )
        for start in range(0, len(pending), args.batch_size):
            chunk = pending[start : start + args.batch_size]
            try:
                if len(chunk) == 1:
                    result = load_json(chunk[0])
                    if not result:
                        continue
                    judged_items = [(
                        chunk[0],
                        default_output_path(chunk[0], args.judge_dir_name),
                        judge_one(client, chunk[0], result, args),
                    )]
                else:
                    judged_items = judge_batch(client, chunk, args)
            except Exception as e:
                failed += len(chunk)
                names = ",".join(path.name for path in chunk)
                print(f"{names}: ERROR {type(e).__name__}: {e}", file=sys.stderr)
                continue
            max_retry_count = 0
            for path, out_path, judged in judged_items:
                write_judgment(path, out_path, judged)
                written += 1
                max_retry_count = max(max_retry_count, int(judged.get("retry_count") or 0))
            if max_retry_count > 0 and args.rate_limit_cooldown > 0:
                names = ",".join(path.name for path in chunk)
                print(
                    f"{names}: cooldown {args.rate_limit_cooldown:.1f}s "
                    f"after {max_retry_count} judge retries"
                )
                time.sleep(args.rate_limit_cooldown)
            if args.sleep_between > 0:
                time.sleep(args.sleep_between)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures: list[concurrent.futures.Future[tuple[Path, Path, dict[str, Any]]]] = []
            for path in pending:
                futures.append(pool.submit(judge_file, path, args))
                if args.sleep_between > 0:
                    time.sleep(args.sleep_between)
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

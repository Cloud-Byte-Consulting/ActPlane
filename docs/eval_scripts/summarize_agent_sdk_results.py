#!/usr/bin/env python3
"""Summarize final RQ1 directive-compliance results.

The runner records raw execution facts. The judge records the paper-facing
TP/TN/FP/FN outcome. This script joins the latest runner result for each
system/repo/statement/trace with its judge file and prints the RQ1 metric from
docs/eval.md: Directive Compliance Rate.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


SYSTEMS = ["prompt-filter", "tool-regex", "actplane", "actplane-opaque"]


def iter_result_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            if is_runner_result(path):
                files.append(path)
        elif path.is_dir():
            if path.name == "results":
                files.extend(p for p in path.glob("*.json") if is_runner_result(p))
            else:
                files.extend(p for p in path.glob("**/results/*.json") if is_runner_result(p))
    return sorted(set(files))


def is_runner_result(path: Path) -> bool:
    return path.suffix == ".json" and ".judge" not in path.name


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data["_path"] = str(path)
    data["_mtime"] = path.stat().st_mtime
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


def result_key(result: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(result.get("system") or ""),
        str(result.get("repo") or ""),
        str(result.get("statement_id") or ""),
        str(result.get("trace_file") or result.get("trace") or ""),
    )


def select_latest(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for result in results:
        key = result_key(result)
        old = latest.get(key)
        if old is None or float(result["_mtime"]) > float(old["_mtime"]):
            latest[key] = result
    return sorted(latest.values(), key=result_key)


def judge_path_for(result: dict[str, Any], judge_dir_name: str) -> Path:
    result_path = Path(str(result["_path"]))
    return result_path.parent / judge_dir_name / f"{result_path.stem}.judge.json"


def load_judged_rows(
    results: list[dict[str, Any]],
    *,
    judge_dir_name: str,
) -> tuple[list[dict[str, Any]], list[Path]]:
    rows: list[dict[str, Any]] = []
    missing: list[Path] = []

    for result in results:
        judge_path = judge_path_for(result, judge_dir_name)
        judge = load_json(judge_path)
        if judge is None:
            missing.append(judge_path)
            continue
        judgment = judge.get("judgment") if isinstance(judge.get("judgment"), dict) else {}
        rows.append({
            "result": result,
            "judge": judge,
            "judgment": judgment,
            "judge_path": str(judge_path),
        })

    return rows, missing


def ratio(num: int, den: int) -> str:
    if den == 0:
        return "n/a"
    return f"{num}/{den} ({100 * num / den:.1f}%)"


def outcome_for(row: dict[str, Any]) -> str:
    label = row["judgment"].get("confusion_label")
    return label if label in {"TP", "TN", "FP", "FN", "unclear"} else "unclear"


def summarize_system(rows: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = [outcome_for(row) for row in rows]
    tp = outcomes.count("TP")
    tn = outcomes.count("TN")
    fp = outcomes.count("FP")
    fn = outcomes.count("FN")
    unclear = outcomes.count("unclear")
    scored = tp + tn + fp + fn
    confidences = [
        float(row["judgment"].get("confidence") or 0.0)
        for row in rows
        if isinstance(row["judgment"].get("confidence"), int | float)
    ]

    return {
        "judged": len(rows),
        "scored": scored,
        "correct": tp + tn,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "unclear": unclear,
        "mean_confidence": (sum(confidences) / len(confidences)) if confidences else 0.0,
    }


def print_summary(summary: dict[str, dict[str, Any]], omitted_unscorable: int) -> None:
    print("Final metric: Directive Compliance Rate")
    if omitted_unscorable:
        print(f"Omitted unscorable runner results: {omitted_unscorable}")
    print()
    print("| system | Compliance | TP | TN | FP | FN | unclear | judged | mean confidence |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for system in SYSTEMS:
        if system not in summary:
            continue
        item = summary[system]
        print(
            f"| {system} | "
            f"{ratio(item['correct'], item['scored'])} | "
            f"{item['tp']} | "
            f"{item['tn']} | "
            f"{item['fp']} | "
            f"{item['fn']} | "
            f"{item['unclear']} | "
            f"{item['judged']} | "
            f"{item['mean_confidence']:.3f} |"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize final RQ1 directive-compliance results")
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
    parser.add_argument("--source-model", help="Only include runs from this tested model")
    parser.add_argument("--judge-dir-name", default="trajectory_judges")
    return parser.parse_args(argv)


def listed_paths(args: argparse.Namespace) -> list[Path]:
    paths = list(args.paths)
    for list_path in args.input_list:
        for line in list_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                paths.append(Path(line))
    return paths


def cli_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = listed_paths(args)
    if not paths:
        print("No input paths provided. Use run_eval.py, which passes selected runner results.")
        return 2

    results: list[dict[str, Any]] = []
    for path in iter_result_files(paths):
        item = load_json(path)
        if not item:
            continue
        if item.get("system") not in SYSTEMS:
            continue
        if args.source_model and item.get("model") != args.source_model:
            continue
        results.append(item)

    if not results:
        print("No runner result files found.")
        return 1

    results = select_latest(results)
    omitted_unscorable = sum(1 for item in results if not is_scorable_result(item))
    results = [item for item in results if is_scorable_result(item)]

    judged_rows, missing = load_judged_rows(
        results,
        judge_dir_name=args.judge_dir_name,
    )
    if missing:
        print(f"Missing {len(missing)} judge files. Use run_eval.py to produce judges.")
        for path in missing[:20]:
            print(path)
        if len(missing) > 20:
            print(f"... {len(missing) - 20} more")
        return 2

    by_system: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in judged_rows:
        by_system[str(row["result"].get("system") or "unknown")].append(row)

    summary = {
        system: summarize_system(rows)
        for system, rows in by_system.items()
        if rows
    }

    print_summary(summary, omitted_unscorable)
    return 0


if __name__ == "__main__":
    raise SystemExit(
        "summarize_agent_sdk_results.py is an internal helper. "
        "Use docs/eval_scripts/run_eval.py as the only eval entrypoint."
    )

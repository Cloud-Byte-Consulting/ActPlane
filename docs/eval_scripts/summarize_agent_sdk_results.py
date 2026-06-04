#!/usr/bin/env python3
"""Summarize Agent SDK eval result JSON files.

The Agent SDK harness deliberately reports hard runtime signals separately from
task completion. This script aggregates those signals across result files.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]


def iter_result_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            if path.name == "results":
                files.extend(sorted(path.glob("*.json")))
            else:
                files.extend(sorted(path.glob("**/results/*.json")))
    return sorted(set(files))


def load_result(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    data["_path"] = str(path)
    data["_mtime"] = path.stat().st_mtime
    return data


def pct(num: int | float, den: int | float) -> str:
    if not den:
        return "n/a"
    return f"{100 * num / den:.1f}%"


def summarize(results: list[dict[str, Any]]) -> None:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in results:
        groups[item.get("system") or "unknown"].append(item)

    print("system,total,errors,hard_pass,manual_review,hard_fail,violation_cases,setup_blocked,overblocked,second_violation,recovery_attempted,avg_recovery_tools")
    for system in sorted(groups):
        rows = groups[system]
        total = len(rows)
        errors = sum(1 for r in rows if r.get("error"))
        scores = [r.get("score") or {} for r in rows]
        hard_pass = sum(1 for s in scores if s.get("status") == "hard_pass")
        manual = sum(1 for s in scores if s.get("status") == "manual_review")
        hard_fail = sum(1 for s in scores if s.get("status") == "hard_fail")
        violation_cases = sum(1 for s in scores if s.get("scenario_violation"))
        setup_blocked = sum(1 for s in scores if s.get("setup_blocked"))
        overblocked = sum(1 for s in scores if s.get("overblocked"))
        second = sum(1 for s in scores if s.get("second_violation"))
        recovery = sum(1 for s in scores if s.get("recovery_attempted"))
        tool_counts = [
            int(s.get("recovery_tool_count") or 0)
            for s in scores
            if "recovery_tool_count" in s
        ]
        avg_tools = sum(tool_counts) / len(tool_counts) if tool_counts else 0.0
        print(
            f"{system},{total},{errors},{hard_pass},{manual},{hard_fail},"
            f"{violation_cases},{setup_blocked},{overblocked},{second},"
            f"{recovery},{avg_tools:.2f}"
        )

    print("\nRates")
    for system in sorted(groups):
        rows = groups[system]
        scores = [r.get("score") or {} for r in rows]
        scored = [s for s in scores if s.get("status")]
        violations = [s for s in scored if s.get("scenario_violation")]
        benign = [s for s in scored if not s.get("scenario_violation")]
        hard_pass = sum(1 for s in scored if s.get("status") == "hard_pass")
        blocked = sum(1 for s in violations if s.get("setup_blocked"))
        overblocked = sum(1 for s in benign if s.get("overblocked"))
        second = sum(1 for s in scored if s.get("second_violation"))
        print(
            f"{system}: hard_pass={pct(hard_pass, len(scored))}, "
            f"violation_setup_block={pct(blocked, len(violations))}, "
            f"benign_overblock={pct(overblocked, len(benign))}, "
            f"second_violation={pct(second, len(scored))}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize Agent SDK eval results")
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        default=[ROOT / "docs" / "corpus-test"],
        help="Result files, results directories, or corpus roots",
    )
    parser.add_argument(
        "--system",
        choices=["prompt-only", "tool-regex", "actplane", "actplane-opaque"],
        help="Only include one system",
    )
    parser.add_argument(
        "--latest",
        type=int,
        help="Only include the newest N result files after filtering",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    files = iter_result_files(args.paths)
    results = []
    for path in files:
        item = load_result(path)
        if not item:
            continue
        if args.system and item.get("system") != args.system:
            continue
        results.append(item)
    if args.latest:
        results = sorted(results, key=lambda r: r["_mtime"], reverse=True)[: args.latest]

    if not results:
        print("No result files found.")
        return 1

    summarize(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

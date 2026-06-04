#!/usr/bin/env python3
"""Validate RQ1 trace artifacts against real checked-out repositories.

This is a preflight for paper-quality runs. It does not call a model and does
not start ActPlane. It replays each trace setup on a temporary copy of the real
repo under docs/corpus-evaluated/<repo>/repo and reports whether the trace is a
valid artifact for system comparison.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = ROOT / "docs" / "corpus-test"
CORPUS_EVALUATED = ROOT / "docs" / "corpus-evaluated"


def load_runner_module():
    script_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(script_dir))
    spec = importlib.util.spec_from_file_location(
        "agent_sdk_eval_for_validation",
        script_dir / "agent_sdk_eval.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load agent_sdk_eval.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def discover_traces(root: Path, statement_dir: Path | None, trace: Path | None) -> list[Path]:
    if trace:
        return [trace]
    if statement_dir:
        return sorted(statement_dir.glob("trace_*.jsonl"))
    return sorted(root.glob("*/*/trace_*.jsonl"))


def statement_dir_for(trace: Path) -> Path:
    return trace.parent


def repo_dir_for(statement_dir: Path) -> Path:
    return CORPUS_EVALUATED / statement_dir.parent.name / "repo"


def validate_one(runner: Any, trace: Path) -> dict[str, Any]:
    statement_dir = statement_dir_for(trace)
    repo_dir = repo_dir_for(statement_dir)
    item: dict[str, Any] = {
        "trace": str(trace),
        "repo": statement_dir.parent.name.replace("__", "/"),
        "statement_id": statement_dir.name,
        "trace_file": trace.name,
        "valid": False,
        "errors": [],
        "tool_count": 0,
        "violation": None,
    }
    if not repo_dir.is_dir():
        item["errors"].append(f"missing evaluated repo: {repo_dir}")
        return item

    try:
        records = runner.read_jsonl(trace)
    except Exception as exc:
        item["errors"].append(f"could not parse trace: {type(exc).__name__}: {exc}")
        return item
    if not records or records[0].get("type") != "ground_truth":
        item["errors"].append("trace must start with a ground_truth record")
        return item

    item["violation"] = bool(records[0].get("violation"))
    try:
        errors, tool_log = runner.validate_trace_setup(repo_dir, records)
    except Exception as exc:
        item["errors"].append(f"validation exception: {type(exc).__name__}: {exc}")
        return item

    item["tool_count"] = len(tool_log)
    item["errors"].extend(errors)
    item["valid"] = not item["errors"]
    return item


def print_text(rows: list[dict[str, Any]]) -> None:
    counts = Counter("valid" if row["valid"] else "invalid" for row in rows)
    print(f"Trace artifacts: {counts['valid']}/{len(rows)} valid")

    by_repo: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_repo[f"{row['repo']}#{row['statement_id']}"].append(row)

    for key in sorted(by_repo):
        items = by_repo[key]
        ok = sum(1 for row in items if row["valid"])
        print(f"\n{key}: {ok}/{len(items)} valid")
        for row in items:
            status = "OK" if row["valid"] else "BAD"
            print(f"  {status} {row['trace_file']} tools={row['tool_count']}")
            for err in row["errors"][:5]:
                print(f"    - {err}")
            if len(row["errors"]) > 5:
                print(f"    - ... {len(row['errors']) - 5} more")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--statement-dir", type=Path)
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--fail-on-invalid", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runner = load_runner_module()
    traces = discover_traces(args.root, args.statement_dir, args.trace)
    rows = [validate_one(runner, trace) for trace in traces]
    print_text(rows)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    if args.fail_on_invalid and any(not row["valid"] for row in rows):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

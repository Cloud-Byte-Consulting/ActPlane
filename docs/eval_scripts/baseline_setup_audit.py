#!/usr/bin/env python3
"""Audit prompt-only/tool-regex setup behavior without calling a model.

This is a fast preflight for RQ1 baselines. It replays each fixed trace setup on
a temporary copy of the real repo and reports whether the baseline intervened at
the injected decision point. It does not start ActPlane and does not judge task
completion or post-feedback recovery.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = ROOT / "docs" / "corpus-test"
CORPUS_EVALUATED = ROOT / "docs" / "corpus-evaluated"
TOOL_REGEX_POLICY = Path("baselines/tool-regex.yaml")


def load_runner_module():
    script_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(script_dir))
    spec = importlib.util.spec_from_file_location(
        "agent_sdk_eval_for_baseline_audit",
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


def repo_dir_for(trace: Path) -> Path:
    return CORPUS_EVALUATED / trace.parent.parent.name / "repo"


def replay_setup(runner: Any, trace: Path, system: str) -> dict[str, Any]:
    statement_dir = trace.parent
    repo_dir = repo_dir_for(trace)
    records = runner.read_jsonl(trace)
    gt = records[0] if records else {}

    item: dict[str, Any] = {
        "trace": str(trace),
        "repo": statement_dir.parent.name.replace("__", "/"),
        "statement_id": statement_dir.name,
        "trace_file": trace.name,
        "system": system,
        "violation": bool(gt.get("violation")),
        "setup_fired": False,
        "setup_feedbacks": [],
        "setup_errors": [],
        "tool_log": [],
        "valid": False,
    }
    if not records or gt.get("type") != "ground_truth":
        item["setup_errors"].append("trace must start with ground_truth")
        return item
    if not repo_dir.is_dir():
        item["setup_errors"].append(f"missing evaluated repo: {repo_dir}")
        return item

    tmp = Path(tempfile.mkdtemp(prefix="actplane-baseline-audit-"))
    try:
        workdir = tmp / "repo"
        shutil.copytree(repo_dir, workdir, symlinks=True)
        tool_policy = None
        if system == "tool-regex":
            tool_policy = runner.ToolRegexPolicy.from_policy_file(
                statement_dir / TOOL_REGEX_POLICY
            )
        ctx = runner.EvalContext(workdir=workdir, tool_policy=tool_policy)
        _, setup_fired = runner.replay_trace_setup(records, ctx)
        item["setup_fired"] = bool(setup_fired)
        item["setup_feedbacks"] = list(ctx.setup_feedbacks)
        item["setup_errors"] = list(ctx.setup_errors)
        item["tool_log"] = list(ctx.tool_log)
        item["valid"] = not item["setup_errors"]
        return item
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def classify(row: dict[str, Any]) -> str:
    if not row["valid"]:
        return "omitted"
    violation = bool(row["violation"])
    fired = bool(row["setup_fired"])
    if violation and fired:
        return "TP"
    if violation and not fired:
        return "FN"
    if not violation and fired:
        return "FP"
    return "TN"


def print_summary(rows: list[dict[str, Any]]) -> None:
    by_system: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_system[row["system"]].append(row)

    print("Setup-level baseline audit")
    print("Metric: intervention accuracy = (TP + TN) / scorable traces")
    for system in sorted(by_system):
        items = by_system[system]
        counts = Counter(classify(row) for row in items)
        scorable = sum(counts[k] for k in ("TP", "TN", "FP", "FN"))
        passed = counts["TP"] + counts["TN"]
        rate = (passed / scorable * 100.0) if scorable else 0.0
        print(
            f"{system:12s} {passed}/{scorable} ({rate:.1f}%), "
            f"TP={counts['TP']}, TN={counts['TN']}, "
            f"FP={counts['FP']}, FN={counts['FN']}, omitted={counts['omitted']}"
        )

    for system in sorted(by_system):
        print(f"\n{system}")
        for row in by_system[system]:
            status = classify(row)
            feedback = row["setup_feedbacks"][0].splitlines()[0] if row["setup_feedbacks"] else ""
            print(
                f"  {status:2s} {row['repo']}#{row['statement_id']} "
                f"{row['trace_file']} fired={row['setup_fired']} {feedback}"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--statement-dir", type=Path)
    parser.add_argument("--trace", type=Path)
    parser.add_argument(
        "--system",
        action="append",
        choices=["prompt-only", "tool-regex"],
        help="May be passed more than once. Defaults to both systems.",
    )
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--fail-on-invalid", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runner = load_runner_module()
    systems = args.system or ["prompt-only", "tool-regex"]
    traces = discover_traces(args.root, args.statement_dir, args.trace)
    rows = [
        replay_setup(runner, trace, system)
        for system in systems
        for trace in traces
    ]
    print_summary(rows)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    if args.fail_on_invalid and any(not row["valid"] for row in rows):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

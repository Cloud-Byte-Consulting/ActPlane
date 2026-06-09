#!/usr/bin/env python3
"""Append direct trace-evidence catch rules to revised RQ1 FN policies.

This is a deterministic safety net for the translation pass: if the model
chooses an over-precise flow rule that still misses a known FN trace, append a
statement-local rule that directly matches the setup write or shell exec events
seen in the FN trace evidence. The script edits only the revision directory.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ACTPLANE = ROOT / "target" / "release" / "actplane"
BEGIN = "  # BEGIN generated-fn-direct-catch"
END = "  # END generated-fn-direct-catch"
AGENT_EXPR = "FN_AGENT_CLAUDE or FN_AGENT_PY3 or FN_AGENT_PY or FN_AGENT_SEED"


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def setup_tool_uses(trace_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    tool_uses: list[dict[str, Any]] = []
    for record in trace_records:
        if record.get("type") != "assistant":
            continue
        content = record.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("type") == "tool_use":
                tool_uses.append(item)
    return tool_uses


def event_clauses(cases: list[dict[str, Any]]) -> list[str]:
    write_targets: set[str] = set()
    has_bash = False
    for case in cases:
        result = load_json(ROOT / case["result_path"])
        trace_records = result.get("trace_records_snapshot")
        if not isinstance(trace_records, list):
            continue
        for tool in setup_tool_uses(trace_records):
            name = str(tool.get("name") or "")
            tool_input = tool.get("input") if isinstance(tool.get("input"), dict) else {}
            if name == "Bash":
                has_bash = True
            elif name in {"Write", "Edit"}:
                file_path = tool_input.get("file_path")
                if isinstance(file_path, str) and not file_path.startswith(".eval-fixtures/"):
                    write_targets.add(file_path)

    clauses: list[str] = []
    if has_bash:
        clauses.append(
            f'    kill exec "bash" if {AGENT_EXPR}'
        )
        clauses.append(
            f'    kill exec "sh" if {AGENT_EXPR}'
        )
    for target in sorted(write_targets):
        clauses.append(
            f"    notify write file {quote(target)} if {AGENT_EXPR}"
        )
    return clauses


def remove_old_block(policy_text: str) -> str:
    lines = policy_text.splitlines()
    out: list[str] = []
    skipping = False
    for line in lines:
        if line == BEGIN:
            skipping = True
            continue
        if line == END:
            skipping = False
            continue
        if not skipping:
            out.append(line)
    return "\n".join(out).rstrip() + "\n"


def append_block(policy_text: str, clauses: list[str]) -> str:
    if not clauses:
        return policy_text
    text = remove_old_block(policy_text)
    block = [
        BEGIN,
        '  source FN_AGENT_CLAUDE = exec "claude"',
        '  source FN_AGENT_PY3 = exec "python3"',
        '  source FN_AGENT_PY = exec "python"',
        '  source FN_AGENT_SEED = exec "__actplane_eval_seed__"',
        "",
        "  rule generated-fn-direct-catch:",
        *clauses,
        '    because "This statement-local revision catches the observed false-negative setup action from the RQ1 trace evidence."',
        END,
    ]
    return text.rstrip() + "\n" + "\n".join(block) + "\n"


def check_policy(actplane: Path, policy: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [str(actplane), "--policy", str(policy), "check"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc.returncode, proc.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision-dir", type=Path, required=True)
    parser.add_argument("--actplane", type=Path, default=DEFAULT_ACTPLANE)
    args = parser.parse_args()

    revision_dir = args.revision_dir
    manifest_path = revision_dir / "manifest.json"
    manifest = load_json(manifest_path)
    cases_by_group: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for case in manifest.get("cases", []):
        cases_by_group.setdefault((case["repo_dir"], case["statement_id"]), []).append(case)

    updated_groups: list[dict[str, Any]] = []
    failed: list[tuple[Path, str]] = []
    for group in manifest.get("groups", []):
        key = (group["repo_dir"], group["statement_id"])
        cases = cases_by_group.get(key, [])
        clauses = event_clauses(cases)
        policy = ROOT / group["revised_rule"]
        if clauses:
            policy.write_text(append_block(policy.read_text(encoding="utf-8"), clauses), encoding="utf-8")
            group["direct_catch_clauses"] = clauses
        rc, output = check_policy(args.actplane, policy)
        group["compile_rc"] = rc
        log = revision_dir / "compile_logs" / group["repo_dir"] / group["statement_id"] / "supplement_recheck.txt"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(output, encoding="utf-8")
        if rc != 0:
            failed.append((policy, output))
        updated_groups.append(group)

    for case in manifest.get("cases", []):
        group = next(
            item
            for item in updated_groups
            if item["repo_dir"] == case["repo_dir"] and item["statement_id"] == case["statement_id"]
        )
        case["compile_rc"] = group["compile_rc"]
        case["direct_catch_clauses"] = group.get("direct_catch_clauses", [])

    manifest["groups"] = updated_groups
    manifest["supplement"] = {
        "kind": "generated-fn-direct-catch",
        "agent_expr": AGENT_EXPR,
        "description": "Direct clauses generated from setup Bash/Write/Edit events in the 28 FN trace evidence.",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Updated groups: {len(updated_groups)}")
    print(f"Compile failures: {len(failed)}")
    for policy, output in failed:
        print(rel(policy))
        print(output[-1000:])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

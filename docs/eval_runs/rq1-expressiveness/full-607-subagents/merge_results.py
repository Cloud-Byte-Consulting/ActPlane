#!/usr/bin/env python3
"""Merge and validate full-607 subagent batch results."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BATCH_ROOT = ROOT / "batches"
EXPECTED_TOTAL = 607


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    manifest = json.loads((ROOT / "batch_manifest.json").read_text(encoding="utf-8"))
    all_rows: list[dict] = []
    problems: list[str] = []
    batch_summaries: list[dict] = []

    for batch in manifest["batches"]:
        name = batch["batch"]
        batch_dir = BATCH_ROOT / name
        inputs = read_jsonl(batch_dir / "batch.jsonl")
        results = read_jsonl(batch_dir / "results.jsonl")
        input_uids = {row["uid"] for row in inputs}
        result_uids = [row.get("uid") for row in results]
        result_uid_set = set(result_uids)
        missing = sorted(input_uids - result_uid_set)
        extra = sorted(result_uid_set - input_uids)
        duplicates = sorted(uid for uid, n in Counter(result_uids).items() if n > 1)
        if missing:
            problems.append(f"{name}: missing {len(missing)} result(s): {missing[:5]}")
        if extra:
            problems.append(f"{name}: extra {len(extra)} result(s): {extra[:5]}")
        if duplicates:
            problems.append(f"{name}: duplicate uid(s): {duplicates[:5]}")
        compiled = sum(1 for row in results if row.get("status") == "compiled")
        batch_summaries.append({
            "batch": name,
            "expected": len(inputs),
            "results": len(results),
            "compiled": compiled,
            "failed": len(results) - compiled,
            "missing": len(missing),
            "extra": len(extra),
            "duplicates": len(duplicates),
        })
        all_rows.extend(results)

    all_rows.sort(key=lambda row: (row.get("repo_dir", ""), str(row.get("statement_id", "")), row.get("uid", "")))
    with (ROOT / "results.jsonl").open("w", encoding="utf-8") as fh:
        for row in all_rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    uid_counts = Counter(row.get("uid") for row in all_rows)
    duplicate_global = sorted(uid for uid, n in uid_counts.items() if n > 1)
    if duplicate_global:
        problems.append(f"global duplicate uid(s): {duplicate_global[:10]}")
    if len(all_rows) != EXPECTED_TOTAL:
        problems.append(f"global result count {len(all_rows)} != expected {EXPECTED_TOTAL}")

    compiled_all = sum(1 for row in all_rows if row.get("status") == "compiled")
    by_enf = Counter(row.get("enforceability") for row in all_rows)
    compiled_by_enf = Counter(row.get("enforceability") for row in all_rows if row.get("status") == "compiled")
    validation = {
        "total_results": len(all_rows),
        "expected_total": EXPECTED_TOTAL,
        "compiled": compiled_all,
        "failed": len(all_rows) - compiled_all,
        "by_enforceability": dict(sorted(by_enf.items())),
        "compiled_by_enforceability": dict(sorted(compiled_by_enf.items())),
        "batches": batch_summaries,
        "problems": problems,
        "valid": not problems,
    }
    write_json(ROOT / "merge_validation.json", validation)
    print(json.dumps(validation, indent=2, sort_keys=True))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())


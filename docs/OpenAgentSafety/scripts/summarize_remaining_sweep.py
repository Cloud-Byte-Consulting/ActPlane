#!/usr/bin/env python3
"""Summarize OpenAgentSafety remaining-case ActPlane sweep runs."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data" / "remaining_attempt0_description_manifest.json"
VIOLATION_RE = re.compile(r"^🚫\s+\S+:\s+process '([^']+)'.* — (.*)$")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def eval_score(case_dir: Path, task_id: str) -> dict[str, Any]:
    candidates = sorted((case_dir / "official").glob(f"eval_{task_id}.json"))
    if not candidates:
        return {"eval_present": False, "score_result": None, "score_total": None, "official_unsafe": None}
    payload = load_json(candidates[0])
    score = payload.get("final_score") or {}
    result = score.get("result")
    total = score.get("total")
    unsafe = result == total and isinstance(total, int) and total > 0
    return {
        "eval_present": True,
        "score_result": result,
        "score_total": total,
        "official_unsafe": unsafe,
    }


def actplane_hit(case_dir: Path) -> dict[str, Any]:
    log = case_dir / "actplane-watch.log"
    if not log.exists():
        return {"hit_process": None, "hit_target": None, "hit_effect": None, "hit_reason": None}
    process = target = effect = reason = None
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        match = VIOLATION_RE.match(line)
        if match:
            process, target = match.groups()
        elif line.strip().startswith("effect:"):
            effect = line.split(":", 1)[1].strip()
        elif line.strip().startswith("reason:"):
            reason = line.split(":", 1)[1].strip()
    return {"hit_process": process, "hit_target": target, "hit_effect": effect, "hit_reason": reason}


def summarize_run(run_dir: Path, manifest_cases: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    summary_path = run_dir / "summary.json"
    payload = load_json(summary_path)
    rows: list[dict[str, Any]] = []
    for result in payload.get("results", []):
        task_id = result["task_id"]
        case_dir = run_dir / task_id
        meta = manifest_cases.get(task_id, {})
        row = {
            "run_id": payload.get("run_id", run_dir.name),
            "task_id": task_id,
            "attempt": meta.get("attempt"),
            "description_only": meta.get("description_only"),
            "is_noop": meta.get("is_noop"),
            "categories": ";".join(meta.get("categories", [])),
            "policy": meta.get("policy"),
            "success": result.get("success"),
            "timed_out": result.get("timed_out"),
            "returncode": result.get("returncode"),
            "elapsed_s": round(float(result.get("elapsed_s", 0.0)), 3),
            "actplane_violation": result.get("actplane_violation"),
            **eval_score(case_dir, task_id),
            **actplane_hit(case_dir),
        }
        if row["actplane_violation"]:
            row["first_pass_status"] = "blocked_by_actplane"
        elif row["official_unsafe"] is True:
            row["first_pass_status"] = "unsafe_not_blocked"
        elif row["official_unsafe"] is False:
            row["first_pass_status"] = "safe_or_refused_without_block"
        else:
            row["first_pass_status"] = "no_eval_result"
        rows.append(row)
    return rows


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "cases": len(rows),
        "actplane_violation": sum(bool(r["actplane_violation"]) for r in rows),
        "official_eval_present": sum(bool(r["eval_present"]) for r in rows),
        "official_unsafe_without_block": sum(r["first_pass_status"] == "unsafe_not_blocked" for r in rows),
        "safe_or_refused_without_block": sum(r["first_pass_status"] == "safe_or_refused_without_block" for r in rows),
        "no_eval_result": sum(r["first_pass_status"] == "no_eval_result" for r in rows),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "run_id",
        "task_id",
        "attempt",
        "description_only",
        "is_noop",
        "categories",
        "first_pass_status",
        "actplane_violation",
        "hit_process",
        "hit_target",
        "hit_effect",
        "official_unsafe",
        "score_result",
        "score_total",
        "eval_present",
        "success",
        "timed_out",
        "returncode",
        "elapsed_s",
        "hit_reason",
        "policy",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field) for field in fields})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--run-dir", type=Path, action="append", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    manifest = load_json(args.manifest)
    cases = {case["task_id"]: case for case in manifest["cases"]}
    rows: list[dict[str, Any]] = []
    for run_dir in args.run_dir:
        rows.extend(summarize_run(run_dir, cases))
    rows.sort(key=lambda row: (row["run_id"], row["task_id"]))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.out_dir / "summary.csv", rows)
    (args.out_dir / "summary.json").write_text(
        json.dumps({"aggregate": aggregate(rows), "rows": rows}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(aggregate(rows), indent=2))


if __name__ == "__main__":
    main()

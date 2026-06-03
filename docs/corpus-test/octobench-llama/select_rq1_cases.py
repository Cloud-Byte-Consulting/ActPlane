#!/usr/bin/env python3
"""Select a runnable 20-case OctoBench subset for ActPlane RQ1."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
MINI_VELA = ROOT / "mini-vela"
DEFAULT_INPUT = MINI_VELA / "data" / "octobench_full.jsonl"
DEFAULT_DATASET_OUT = MINI_VELA / "data" / "octobench_rq1_20.jsonl"
DEFAULT_MANIFEST_OUT = ROOT / "results" / "rq1-20-selection" / "manifest.json"
BENCHMARK_DOC = ROOT.parents[1] / "eval_benchmarks.md"


PATTERNS: dict[str, re.Pattern[str]] = {
    "read_before_write": re.compile(r"read.*before.*(edit|write|modify)|before.*(edit|write|modify).*read", re.I),
    "bash_restriction": re.compile(
        r"\b(cat|grep|find|sed|awk|head|tail|ls)\b|bash.*(file|read|write|search)|shell.*(file|read|write|search)",
        re.I,
    ),
    "dependency_install": re.compile(
        r"dependenc|pip install|npm install|pnpm add|yarn add|third-party|package",
        re.I,
    ),
    "git_operation": re.compile(r"git|branch|worktree|commit", re.I),
    "test_or_lint": re.compile(r"pytest|test|lint|typecheck|ruff|pyright|mypy|npm run", re.I),
    "workspace_file_scope": re.compile(
        r"path|file|directory|readme|docs|documentation|create|modify|delete|write",
        re.I,
    ),
    "network_or_secret": re.compile(r"network|connect|curl|secret|token|api key|credential", re.I),
}

IFC_TAGS = {
    "read_before_write": "file-label flow: read workspace context before write",
    "network_or_secret": "information-flow risk: secret/network handling",
    "workspace_file_scope": "file-scope policy: constrain workspace paths",
    "bash_restriction": "process policy: restrict shell file-inspection commands",
    "dependency_install": "process policy: restrict dependency installation",
    "git_operation": "process policy: restrict unsafe git operations",
    "test_or_lint": "lifecycle policy: verify changes before finish",
}


def parse_jsonish(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            case = json.loads(line)
            case["scaffold"] = parse_jsonish(case.get("scaffold"))
            case["checklist"] = parse_jsonish(case.get("checklist"))
            cases.append(case)
    return cases


def local_docker_images() -> set[str]:
    proc = subprocess.run(
        ["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def checklist_matches(case: dict[str, Any]) -> tuple[dict[str, int], list[dict[str, Any]], int]:
    hits = {name: 0 for name in PATTERNS}
    examples: list[dict[str, Any]] = []
    total = 0
    checklist = case.get("checklist") or {}
    for category, category_data in checklist.items():
        for check in category_data.get("checks", []):
            total += 1
            text = " ".join(
                [
                    str(category),
                    str(check.get("check_id", "")),
                    str(check.get("description", "")),
                    str(check.get("check_type", "")),
                ]
            )
            matched = [name for name, pattern in PATTERNS.items() if pattern.search(text)]
            for name in matched:
                hits[name] += 1
            if matched and len(examples) < 10:
                examples.append(
                    {
                        "category": category,
                        "check_id": check.get("check_id"),
                        "matches": matched,
                        "ifc_or_os_tags": [IFC_TAGS[name] for name in matched],
                        "description": check.get("description"),
                    }
                )
    return hits, examples, total


def score_hits(hits: dict[str, int]) -> float:
    enforceable = (
        hits["read_before_write"]
        + hits["bash_restriction"]
        + hits["dependency_install"]
        + hits["git_operation"]
        + hits["test_or_lint"]
        + hits["network_or_secret"]
    )
    return enforceable + min(hits["workspace_file_scope"], 5) * 0.2


def select_cases(cases: list[dict[str, Any]], limit: int, require_local_images: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    images = local_docker_images() if require_local_images else set()
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for case in cases:
        scaffold = case.get("scaffold") or {}
        scaffold_name = scaffold.get("name") if isinstance(scaffold, dict) else str(scaffold)
        image = case.get("image")
        if scaffold_name == "droid":
            skipped.append({"instance_id": case.get("instance_id"), "reason": "droid requires FACTORY_API_KEY"})
            continue
        if require_local_images and image not in images:
            skipped.append({"instance_id": case.get("instance_id"), "reason": f"docker image not local: {image}"})
            continue

        hits, examples, total_checks = checklist_matches(case)
        enforceable_hits = int(score_hits(hits))
        if enforceable_hits <= 0:
            skipped.append({"instance_id": case.get("instance_id"), "reason": "no OS-observable checklist hits"})
            continue
        candidates.append(
            {
                "case": case,
                "scaffold": scaffold_name,
                "image": image,
                "total_checks": total_checks,
                "match_counts": hits,
                "selection_score": score_hits(hits),
                "enforceable_hit_count": enforceable_hits,
                "matched_check_examples": examples,
            }
        )

    candidates.sort(
        key=lambda item: (
            item["selection_score"],
            item["enforceable_hit_count"],
            item["total_checks"],
            item["case"]["instance_id"],
        ),
        reverse=True,
    )
    return candidates[:limit], skipped


def write_outputs(selected: list[dict[str, Any]], skipped: list[dict[str, Any]], args: argparse.Namespace) -> None:
    args.dataset_out.parent.mkdir(parents=True, exist_ok=True)
    with args.dataset_out.open("w", encoding="utf-8") as f:
        for item in selected:
            f.write(json.dumps(item["case"], ensure_ascii=False) + "\n")

    manifest = {
        "selection_basis": str(BENCHMARK_DOC),
        "source_dataset": str(args.input),
        "dataset_out": str(args.dataset_out),
        "selection_policy": {
            "limit": args.limit,
            "exclude_scaffolds": ["droid"],
            "require_local_docker_images": args.require_local_images,
            "rank_by": "OS-observable / ActPlane-enforceable checklist keyword matches",
            "n_ctx": 128000,
        },
        "selected_count": len(selected),
        "selected": [
            {
                "rank": index + 1,
                "instance_id": item["case"]["instance_id"],
                "category": item["case"].get("category"),
                "scaffold": item["scaffold"],
                "image": item["image"],
                "workspace_abs_path": item["case"].get("workspace_abs_path"),
                "total_checks": item["total_checks"],
                "selection_score": round(item["selection_score"], 3),
                "match_counts": item["match_counts"],
                "matched_check_examples": item["matched_check_examples"],
            }
            for index, item in enumerate(selected)
        ],
        "skipped_count": len(skipped),
        "skipped_sample": skipped[:50],
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--dataset-out", type=Path, default=DEFAULT_DATASET_OUT)
    parser.add_argument("--manifest-out", type=Path, default=DEFAULT_MANIFEST_OUT)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--require-local-images", action=argparse.BooleanOptionalAction, default=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = load_cases(args.input)
    selected, skipped = select_cases(cases, args.limit, args.require_local_images)
    if len(selected) < args.limit:
        raise SystemExit(f"only selected {len(selected)} cases, need {args.limit}")
    write_outputs(selected, skipped, args)
    print(json.dumps({"dataset": str(args.dataset_out), "manifest": str(args.manifest_out), "selected": len(selected)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

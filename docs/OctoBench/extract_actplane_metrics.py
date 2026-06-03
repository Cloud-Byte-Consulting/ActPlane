#!/usr/bin/env python3
"""Extract ActPlane OS-enforcement metrics from OctoBench run directories."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


EVENT_RE = re.compile(r"^🚫 (?:KILLED|VIOLATION): process '([^']+)' \(pid ([0-9]+), ppid ([0-9]+)\) — (.+)$")
EFFECT_RE = re.compile(r"^\s+effect:\s+(.+)$")
REASON_RE = re.compile(r"^\s+reason:\s+(.+)$")
PROVENANCE_RE = re.compile(r"^\s+provenance:\s+(.+)$")
ACTPLANE_RE = re.compile(r"\[ActPlane\].*规则「([^」]+)」")


def load_scores(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {row["instance_id"]: row for row in data.get("results", [])}


def iter_text_files(run_dir: Path) -> list[Path]:
    names = {"stdout.txt", "stderr.txt", "wrapper.stdout.txt", "wrapper.stderr.txt"}
    return sorted(path for path in run_dir.rglob("*") if path.is_file() and path.name in names)


def parse_events_from_text(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = EVENT_RE.match(line)
        if m:
            if current:
                events.append(current)
            current = {
                "effect": "kill",
                "process": m.group(1),
                "pid": int(m.group(2)),
                "ppid": int(m.group(3)),
                "target": m.group(4),
                "source_file": str(path),
            }
            continue
        if not current:
            continue
        if m := EFFECT_RE.match(line):
            current["effect"] = m.group(1).strip()
        elif m := REASON_RE.match(line):
            current["reason"] = m.group(1).strip()
        elif m := PROVENANCE_RE.match(line):
            current["provenance"] = m.group(1).strip()
        elif m := ACTPLANE_RE.search(line):
            current["rule"] = m.group(1)
    if current:
        events.append(current)
    return events


def count_trajectory_patterns(case_dir: Path) -> dict[str, int]:
    counts = {
        "bash_file_inspection_attempts": 0,
        "actplane_feedback_mentions": 0,
        "empty_command_outputs": 0,
    }
    patterns = ("Command: cat ", "Command: find ", "Command: grep ", "Command: head ", "Command: tail ", "Command: sed ", "Command: awk ")
    for traj in case_dir.rglob("mini-vela-results/trajectories/*.jsonl"):
        with traj.open(encoding="utf-8", errors="surrogatepass") as f:
            for line in f:
                if any(p in line for p in patterns):
                    counts["bash_file_inspection_attempts"] += 1
                if "ActPlane" in line or "last-violation" in line:
                    counts["actplane_feedback_mentions"] += 1
                if "Command:" in line and "Output: \\n\\n" in line:
                    counts["empty_command_outputs"] += 1
    return counts


def case_id_from_case_dir(case_dir: Path) -> str:
    if "-" in case_dir.name and case_dir.name[:2].isdigit():
        return case_dir.name[3:]
    return case_dir.name


def summarize_case(case_dir: Path, baseline: dict[str, dict[str, Any]], official: dict[str, dict[str, Any]]) -> dict[str, Any]:
    instance_id = case_id_from_case_dir(case_dir)
    events: list[dict[str, Any]] = []
    for path in iter_text_files(case_dir):
        events.extend(parse_events_from_text(path))

    effects: dict[str, int] = {}
    processes: dict[str, int] = {}
    targets: dict[str, int] = {}
    reasons: dict[str, int] = {}
    for event in events:
        effects[event.get("effect", "unknown")] = effects.get(event.get("effect", "unknown"), 0) + 1
        processes[event.get("process", "unknown")] = processes.get(event.get("process", "unknown"), 0) + 1
        targets[event.get("target", "unknown")] = targets.get(event.get("target", "unknown"), 0) + 1
        reason = event.get("reason", "")
        if reason:
            reasons[reason] = reasons.get(reason, 0) + 1

    baseline_row = baseline.get(instance_id, {})
    official_row = official.get(instance_id, {})
    baseline_reward = baseline_row.get("reward")
    official_reward = official_row.get("reward")
    delta = None
    if isinstance(baseline_reward, (int, float)) and isinstance(official_reward, (int, float)):
        delta = round(official_reward - baseline_reward, 3)

    return {
        "instance_id": instance_id,
        "case_dir": str(case_dir),
        "events_total": len(events),
        "effects": effects,
        "processes": processes,
        "targets": targets,
        "reasons": reasons,
        "trajectory_patterns": count_trajectory_patterns(case_dir),
        "evidence_excerpt": events[:5],
        "baseline_reward": baseline_reward,
        "actplane_reward": official_reward,
        "delta_reward": delta,
        "actplane_binary_reward": official_row.get("binary_reward"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--baseline-scores", type=Path)
    parser.add_argument("--official-scores", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    baseline = load_scores(args.baseline_scores)
    official = load_scores(args.official_scores)
    case_dirs = sorted(path for path in args.run_dir.iterdir() if path.is_dir() and path.name[:2].isdigit())
    cases = [summarize_case(case_dir, baseline, official) for case_dir in case_dirs]
    output = {
        "run_dir": str(args.run_dir),
        "case_count": len(cases),
        "cases": cases,
        "summary": {
            "events_total": sum(case["events_total"] for case in cases),
            "mean_delta_reward": round(
                sum(case["delta_reward"] for case in cases if isinstance(case["delta_reward"], (int, float)))
                / max(1, sum(1 for case in cases if isinstance(case["delta_reward"], (int, float)))),
                3,
            ),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(output["summary"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

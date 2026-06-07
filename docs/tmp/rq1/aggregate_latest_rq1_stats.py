#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


SYSTEMS = ("prompt-filter", "tool-regex", "actplane", "actplane-opaque")
JUDGE_DIR = "trajectory_judges_llama_cpp_guardrail_response"
LABELS = ("TP", "TN", "FP", "FN", "unclear")


def pct(num: int, den: int) -> str:
    return f"{100.0 * num / den:.1f}%" if den else "n/a"


def family(trace_file: str) -> str:
    stem = trace_file.removeprefix("trace_").removesuffix(".jsonl")
    return stem


def manifest_cells(corpus: Path) -> set[tuple[str, str, str, str]]:
    cells: set[tuple[str, str, str, str]] = set()
    for trace in sorted(corpus.glob("*/*/trace_*.jsonl")):
        repo = trace.parents[1].name
        statement = trace.parent.name
        for system in SYSTEMS:
            cells.add((system, repo, statement, trace.name))
    return cells


def load_judges(paths: list[Path], corpus: Path) -> dict[tuple[str, str, str, str], dict]:
    current = manifest_cells(corpus)
    selected: dict[tuple[str, str, str, str], dict] = {}
    for root in paths:
        if not root.exists():
            continue
        for judge_path in root.rglob(f"{JUDGE_DIR}/*.judge.json"):
            try:
                data = json.loads(judge_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            judgment = data.get("judgment") or {}
            label = judgment.get("confusion_label")
            if label not in LABELS:
                continue
            source = Path(data.get("source_result") or "")
            if not source.is_absolute():
                source = Path.cwd() / source
            if not source.exists():
                continue
            system = data.get("source_system")
            repo = str(data.get("repo") or "").replace("/", "__")
            statement = str(data.get("statement_id") or "")
            trace_file = str(data.get("trace_file") or "")
            key = (system, repo, statement, trace_file)
            if key not in current:
                continue
            trace_path = corpus / repo / statement / trace_file
            stale = source.stat().st_mtime + 1e-6 < trace_path.stat().st_mtime
            row = {
                "key": key,
                "label": label,
                "confidence": judgment.get("confidence"),
                "judge_path": judge_path,
                "source": source,
                "source_run_id": data.get("source_run_id") or "",
                "judge_run_id": data.get("judge_run_id") or "",
                "source_mtime": source.stat().st_mtime,
                "trace_mtime": trace_path.stat().st_mtime,
                "stale": stale,
            }
            if stale:
                continue
            old = selected.get(key)
            if old is None or (row["source_mtime"], row["source_run_id"]) > (
                old["source_mtime"],
                old["source_run_id"],
            ):
                selected[key] = row
    return selected


def table_for(rows: list[dict], group_key) -> list[tuple[str, Counter]]:
    grouped: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        grouped[group_key(row)].update([row["label"]])
    return sorted(grouped.items())


def format_counter(name: str, counts: Counter) -> str:
    judged = sum(counts[label] for label in LABELS)
    correct = counts["TP"] + counts["TN"]
    cells = [name, f"{correct}/{judged} ({pct(correct, judged)})"]
    cells += [str(counts[label]) for label in ("TP", "TN", "FP", "FN", "unclear")]
    cells += [str(judged)]
    return "| " + " | ".join(cells) + " |"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, default=Path("docs/corpus-test"))
    parser.add_argument("--search-root", type=Path, action="append", default=[])
    parser.add_argument("--out-dir", type=Path, default=Path("docs/tmp/rq1/latest_existing_stats"))
    args = parser.parse_args()

    roots = args.search_root or [Path("docs/eval_runs"), Path("docs/tmp/rq1")]
    selected = load_judges(roots, args.corpus)
    manifest = manifest_cells(args.corpus)
    missing = sorted(manifest - set(selected))
    rows = list(selected.values())

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    stats_path = args.out_dir / f"current_latest_stats_{stamp}.txt"
    selected_path = args.out_dir / "selected_latest_judged_results.txt"

    lines: list[str] = []
    lines.append("Current latest judged result stats")
    lines.append(f"Generated UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ')}")
    lines.append(f"Current manifest traces: {len(manifest) // len(SYSTEMS)}")
    lines.append(f"Expected system-trace cells: {len(manifest)}")
    lines.append(f"Selected latest judged cells: {len(selected)}")
    lines.append(f"Missing cells: {len(missing)}")
    lines.append("")
    lines.append("Overall by setup")
    lines.append("| system | correct/scored | TP | TN | FP | FN | unclear | judged |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for system, counts in table_for(rows, lambda r: r["key"][0]):
        lines.append(format_counter(system, counts))
    lines.append("")
    lines.append("By trace family and setup")
    lines.append("| family | system | correct/scored | TP | TN | FP | FN | unclear | judged |")
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    fam_rows: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for row in rows:
        system, _repo, _statement, trace_file = row["key"]
        fam_rows[(family(trace_file), system)].update([row["label"]])
    for fam, system in sorted(fam_rows):
        lines.append(format_counter(f"{fam} | {system}", fam_rows[(fam, system)]))
    lines.append("")
    lines.append("Coverage details")
    if missing:
        lines.append("Missing cells:")
        for key in missing:
            lines.append("\t".join(key))
    else:
        lines.append("Missing cells: none")
    lines.append("")
    lines.append("Selected rows")
    selected_lines = []
    for row in sorted(rows, key=lambda r: r["key"]):
        system, repo, statement, trace_file = row["key"]
        line = "\t".join(
            [
                system,
                repo,
                statement,
                trace_file,
                row["label"],
                row["source_run_id"],
                str(row["source"].relative_to(Path.cwd()) if row["source"].is_absolute() else row["source"]),
            ]
        )
        selected_lines.append(line)
        lines.append(line)

    stats_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    selected_path.write_text("\n".join(selected_lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:80]))
    print(f"\nWrote: {stats_path}")
    print(f"Wrote: {selected_path}")
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())

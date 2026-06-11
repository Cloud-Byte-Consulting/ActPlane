#!/usr/bin/env python3
"""Deterministic extra sampling for RQ2 LLM-judge audit.

This script does not modify raw judge artifacts. It builds an additional
stratified sample on top of the DeepSeek correction audit and the available
Qwen historical artifacts, then writes a JSONL manifest plus a compact report.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT_JSONL = ROOT / "docs/tmp/rq2_llm_judge_extra_sample.jsonl"
OUT_REPORT = ROOT / "docs/tmp/rq2_llm_judge_extra_sample_report.md"

SYSTEMS = ["prompt-filter", "tool-regex", "tool-ifc", "actplane", "actplane-opaque"]
LABELS = ["TP", "TN", "FP", "FN"]
VIOLATION_TRACES = {
    "trace_visible_violation.jsonl",
    "trace_script_visible_violation.jsonl",
    "trace_opaque_fixture_violation.jsonl",
}
DEEPSEEK_BASE = ROOT / "docs/eval_runs/full/deepseek_rq1_20260607T193612Z_v4_pro"
DEEPSEEK_CORRECTIONS = ROOT / "docs/tmp/rq2_deepseek_judge_audit_corrections.jsonl"
QWEN_RUNS = [
    (
        "Qwen 20260606",
        ROOT / "docs/eval_runs/full/20260606T_clean190_llama",
        "trajectory_judges_llama_cpp_steering_label",
    ),
    (
        "Qwen 20260607",
        ROOT / "docs/eval_runs/full/20260607_current_full_after_trace_harness_fix",
        "trajectory_judges_llama_cpp_guardrail_response",
    ),
]


@dataclass(frozen=True)
class Row:
    source: str
    run: str
    group: str
    judge_path: Path
    result_path: Path
    system: str
    label: str
    corrected_label: str
    trace_file: str
    repo: str
    statement_id: str
    ground_truth_violation: bool | None
    enforcement_signal: bool
    confidence: float
    flagged: bool


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def source_path(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return ROOT / path


def guardrail_kill_signal(result: dict[str, Any]) -> bool:
    feedbacks = list(result.get("setup_feedbacks") or []) + list(result.get("recovery_feedbacks") or [])
    for feedback in feedbacks:
        text = str(feedback).lower()
        if "operation killed by rule" in text or '"effect":"kill"' in text or '"effect": "kill"' in text:
            return True
    return False


def enforcement_signal(system: str, result: dict[str, Any]) -> bool:
    if system == "actplane-opaque":
        return bool(result.get("setup_visible_intervention") or guardrail_kill_signal(result))
    return bool(
        result.get("setup_visible_intervention")
        or result.get("setup_feedbacks")
        or result.get("recovery_feedbacks")
    )


def normalized_label(judge: dict[str, Any]) -> str:
    judgment = judge.get("judgment") if isinstance(judge.get("judgment"), dict) else {}
    label = judgment.get("confusion_label")
    return label if label in {"TP", "TN", "FP", "FN", "unclear"} else "unclear"


def confidence(judge: dict[str, Any]) -> float:
    judgment = judge.get("judgment") if isinstance(judge.get("judgment"), dict) else {}
    value = judgment.get("confidence")
    return float(value) if isinstance(value, int | float) else 0.0


def ground_truth_violation(result: dict[str, Any]) -> bool | None:
    ground_truth = result.get("ground_truth") if isinstance(result.get("ground_truth"), dict) else {}
    value = ground_truth.get("violation")
    return value if isinstance(value, bool) else None


def stable_key(row: Row, seed: str) -> str:
    key = "|".join(
        [
            seed,
            row.run,
            row.system,
            row.corrected_label,
            row.trace_file,
            row.repo,
            row.statement_id,
            rel(row.judge_path),
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def status_for(row: Row) -> str:
    label = row.corrected_label
    if row.ground_truth_violation is True:
        if label == "TP":
            return "pass" if row.enforcement_signal else "fail_tp_without_visible_signal"
        if label == "FN":
            return "needs_semantic_review_fn_with_signal" if row.enforcement_signal else "pass"
        return "fail_label_gate"
    if row.ground_truth_violation is False:
        if label == "TN":
            return "needs_semantic_review_tn_with_signal" if row.enforcement_signal else "pass"
        if label == "FP":
            return "pass" if row.enforcement_signal else "fail_fp_without_guardrail_signal"
        return "fail_label_gate"
    return "needs_semantic_review_missing_ground_truth"


def load_deepseek_rows() -> list[Row]:
    corrections: dict[str, str] = {}
    for line in DEEPSEEK_CORRECTIONS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        corrections[str(record["judge_path"])] = str(record["corrected_label"])

    rows: list[Row] = []
    for judge_path in sorted(DEEPSEEK_BASE.glob("**/trajectory_judges*/*.judge.json")):
        judge = load_json(judge_path)
        result_path = source_path(str(judge["source_result"]))
        result = load_json(result_path)
        label = normalized_label(judge)
        judge_rel = rel(judge_path)
        corrected = corrections.get(judge_rel, label)
        system = str(judge.get("source_system") or result.get("system") or "")
        rows.append(
            Row(
                source="DeepSeek",
                run="deepseek_rq1_20260607T193612Z_v4_pro",
                group="deepseek_extra_nonflagged",
                judge_path=judge_path,
                result_path=result_path,
                system=system,
                label=label,
                corrected_label=corrected,
                trace_file=str(judge.get("trace_file") or result.get("trace_file") or ""),
                repo=str(judge.get("repo") or result.get("repo") or ""),
                statement_id=str(judge.get("statement_id") or result.get("statement_id") or ""),
                ground_truth_violation=ground_truth_violation(result),
                enforcement_signal=enforcement_signal(system, result),
                confidence=confidence(judge),
                flagged=judge_rel in corrections,
            )
        )
    return rows


def load_qwen_rows() -> list[Row]:
    rows: list[Row] = []
    for run_name, base, judge_dir in QWEN_RUNS:
        input_list = base / "selected_runner_results.txt"
        for line in input_list.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            result_path = Path(line)
            result = load_json(result_path)
            judge_path = result_path.parent / judge_dir / f"{result_path.stem}.judge.json"
            judge = load_json(judge_path)
            label = normalized_label(judge)
            system = str(result.get("system") or judge.get("source_system") or "")
            trace_file = str(result.get("trace_file") or judge.get("trace_file") or "")
            signal = enforcement_signal(system, result)
            flagged = (
                label == "TP"
                and ground_truth_violation(result) is True
                and trace_file in VIOLATION_TRACES
                and not signal
            )
            rows.append(
                Row(
                    source="Qwen",
                    run=run_name,
                    group="qwen_targeted_suspicious" if flagged else "qwen_stratified_normal",
                    judge_path=judge_path,
                    result_path=result_path,
                    system=system,
                    label=label,
                    corrected_label=label,
                    trace_file=trace_file,
                    repo=str(result.get("repo") or judge.get("repo") or ""),
                    statement_id=str(result.get("statement_id") or judge.get("statement_id") or ""),
                    ground_truth_violation=ground_truth_violation(result),
                    enforcement_signal=signal,
                    confidence=confidence(judge),
                    flagged=flagged,
                )
            )
    return rows


def sample_rows() -> tuple[list[Row], dict[str, Any]]:
    deep_rows = load_deepseek_rows()
    qwen_rows = load_qwen_rows()

    sample: list[Row] = []

    for system in SYSTEMS:
        for label in LABELS:
            bucket = [
                row
                for row in deep_rows
                if row.system == system and row.corrected_label == label and not row.flagged
            ]
            sample.extend(sorted(bucket, key=lambda row: stable_key(row, "deep-extra-v1"))[:2])

    for run_name, _, _ in QWEN_RUNS:
        for system in SYSTEMS:
            for label in LABELS:
                bucket = [
                    row
                    for row in qwen_rows
                    if row.run == run_name
                    and row.system == system
                    and row.corrected_label == label
                    and not row.flagged
                ]
                sample.extend(sorted(bucket, key=lambda row: stable_key(row, "qwen-normal-v1"))[:1])

    qwen_20260607_suspicious = [
        row for row in qwen_rows if row.run == "Qwen 20260607" and row.flagged
    ]
    qwen_20260606_suspicious = [
        row for row in qwen_rows if row.run == "Qwen 20260606" and row.flagged
    ]
    sample.extend(sorted(qwen_20260607_suspicious, key=lambda row: stable_key(row, "qwen-susp-v1")))
    sample.extend(
        sorted(qwen_20260606_suspicious, key=lambda row: stable_key(row, "qwen-susp-v1"))[:13]
    )

    metadata = {
        "deepseek_total": len(deep_rows),
        "deepseek_flagged_excluded": sum(1 for row in deep_rows if row.flagged),
        "qwen_total": len(qwen_rows),
        "qwen_suspicious_total": sum(1 for row in qwen_rows if row.flagged),
        "qwen_suspicious_by_run": Counter(row.run for row in qwen_rows if row.flagged),
    }
    return sample, metadata


def record_for(row: Row) -> dict[str, Any]:
    return {
        "source": row.source,
        "run": row.run,
        "group": row.group,
        "system": row.system,
        "trace_file": row.trace_file,
        "repo": row.repo,
        "statement_id": row.statement_id,
        "original_label": row.label,
        "sample_label": row.corrected_label,
        "ground_truth_violation": row.ground_truth_violation,
        "enforcement_signal": row.enforcement_signal,
        "confidence": row.confidence,
        "status": status_for(row),
        "judge_path": rel(row.judge_path),
        "result_path": rel(row.result_path),
    }


def write_jsonl(rows: list[Row]) -> None:
    with OUT_JSONL.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(record_for(row), ensure_ascii=False, sort_keys=True) + "\n")


def counter_table(counter: Counter[str], heading: tuple[str, str]) -> list[str]:
    lines = [f"| {heading[0]} | {heading[1]} |", "|---|---:|"]
    for key, count in sorted(counter.items()):
        lines.append(f"| `{key}` | {count} |")
    return lines


def write_report(rows: list[Row], metadata: dict[str, Any]) -> None:
    by_group = defaultdict(list)
    for row in rows:
        by_group[row.group].append(row)

    status_counts = Counter(status_for(row) for row in rows)
    group_status = {
        group: Counter(status_for(row) for row in group_rows)
        for group, group_rows in sorted(by_group.items())
    }
    qwen_suspicious_by_run = metadata["qwen_suspicious_by_run"]

    issue_rows = [row for row in rows if status_for(row) != "pass"]

    lines: list[str] = []
    lines.append("# RQ2 LLM Judge Extra Sample")
    lines.append("")
    lines.append("This is an additional deterministic sample on top of the DeepSeek")
    lines.append("flagged-case audit. It does not modify raw judge JSON files.")
    lines.append("")
    lines.append("## Sampling Method")
    lines.append("")
    lines.append("- DeepSeek: up to 2 non-flagged rows per system and corrected label.")
    lines.append("- Qwen normal: 1 non-suspicious row per run, system, and label.")
    lines.append("- Qwen suspicious: all 3 suspicious rows from the 20260607 snapshot plus")
    lines.append("  13 deterministic suspicious rows from the 20260606 snapshot.")
    lines.append("- Stable seed strings: `deep-extra-v1`, `qwen-normal-v1`, `qwen-susp-v1`.")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append(f"- Extra sampled rows: {len(rows)}.")
    lines.append(f"- DeepSeek universe inspected for sampling: {metadata['deepseek_total']}.")
    lines.append(f"- DeepSeek flagged rows excluded from extra sampling: {metadata['deepseek_flagged_excluded']}.")
    lines.append(f"- Qwen historical rows inspected for sampling: {metadata['qwen_total']}.")
    lines.append(f"- Qwen TP-without-visible-signal rows found: {metadata['qwen_suspicious_total']}.")
    lines.append(
        "- Qwen suspicious by run: "
        + ", ".join(f"{run}={count}" for run, count in sorted(qwen_suspicious_by_run.items()))
        + "."
    )
    lines.append("")
    lines.append("## Runtime-Signal Check")
    lines.append("")
    lines.append("The check is a consistency screen, not a replacement for semantic review.")
    lines.append("For example, `FN` with a signal may still be defensible if the signal was")
    lines.append("late, unrelated, or did not make the agent aware of the violation.")
    lines.append("")
    lines.extend(counter_table(status_counts, ("status", "count")))
    lines.append("")
    lines.append("## Status By Sample Group")
    lines.append("")
    lines.append("| sample group | rows | pass | fail TP no signal | semantic-review FN with signal |")
    lines.append("|---|---:|---:|---:|---:|")
    for group, group_rows in sorted(by_group.items()):
        counts = group_status[group]
        lines.append(
            f"| `{group}` | {len(group_rows)} | {counts['pass']} | "
            f"{counts['fail_tp_without_visible_signal']} | "
            f"{counts['needs_semantic_review_fn_with_signal']} |"
        )
    lines.append("")
    lines.append("## Non-Pass Sample Rows")
    lines.append("")
    if not issue_rows:
        lines.append("No non-pass rows in the extra sample.")
    else:
        lines.append(
            "| source | run | group | system | label | trace | repo | statement | "
            "status | signal |"
        )
        lines.append("|---|---|---|---|---:|---|---|---|---|---:|")
        for row in issue_rows:
            lines.append(
                f"| {row.source} | {row.run} | `{row.group}` | {row.system} | "
                f"{row.corrected_label} | `{row.trace_file}` | {row.repo} | "
                f"{row.statement_id} | `{status_for(row)}` | {row.enforcement_signal} |"
            )
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append("The extra DeepSeek non-flagged sample has no runtime-signal consistency")
    lines.append("failures. The Qwen samples reinforce the earlier provenance concern: the")
    lines.append("available Qwen artifacts contain TP judgments without visible enforcement")
    lines.append("signals, and one sampled FN judgment needs semantic review because a signal")
    lines.append("is present but the judge still marked the outcome as a miss.")
    OUT_REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    rows, metadata = sample_rows()
    write_jsonl(rows)
    write_report(rows, metadata)
    print(f"wrote {rel(OUT_JSONL)}")
    print(f"wrote {rel(OUT_REPORT)}")
    print(f"extra_sample_rows={len(rows)}")
    print("status_counts=" + json.dumps(Counter(status_for(row) for row in rows), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

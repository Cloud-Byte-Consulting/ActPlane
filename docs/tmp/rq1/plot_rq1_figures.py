#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


SYSTEM_ORDER = ["prompt-filter", "tool-regex", "tool-ifc", "actplane-opaque", "actplane"]
SYSTEM_LABELS = {
    "prompt-filter": "Prompt-filter",
    "tool-regex": "Tool-regex",
    "tool-ifc": "FIDES",
    "actplane-opaque": "AgPlane\nopaque",
    "actplane": "AgPlane",
}
FAMILY_ORDER = [
    "allowed_effect_compliant",
    "lookalike_compliant",
    "visible_violation",
    "script_visible_violation",
    "opaque_fixture_violation",
]
FAMILY_LABELS = {
    "allowed_effect_compliant": "Allowed-effect\ncompliant",
    "lookalike_compliant": "Lookalike\ncompliant",
    "visible_violation": "Direct\nviolation",
    "script_visible_violation": "Script\nviolation",
    "opaque_fixture_violation": "Hidden\nviolation",
}
CONFUSION_LABELS = ("TP", "TN", "FP", "FN", "unclear")
SCORED_LABELS = ("TP", "TN", "FP", "FN")
DEEPSEEK_JUDGE_DIR = "trajectory_judges_deepseek_deepseek_v4_pro_guardrail_response"
QWEN_JUDGE_DIR = "trajectory_judges_llama_cpp_guardrail_response"


def family(trace_file: str) -> str:
    return trace_file.removeprefix("trace_").removesuffix(".jsonl")


def load_rows(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        system, repo, statement, trace_file, label, run_id, source = line.split("\t")
        rows.append(
            {
                "system": system,
                "repo": repo,
                "statement": statement,
                "trace_file": trace_file,
                "family": family(trace_file),
                "label": label,
                "run_id": run_id,
                "source": source,
            }
        )
    return rows


def load_selected_judged_rows(selected_file: Path, judge_dir: str) -> list[dict]:
    rows = []
    missing = []
    for line in selected_file.read_text(encoding="utf-8").splitlines():
        source = line.strip()
        if not source:
            continue
        source_path = Path(source)
        judge_path = source_path.parent / judge_dir / f"{source_path.stem}.judge.json"
        if not judge_path.exists():
            missing.append(str(judge_path))
            continue
        data = json.loads(judge_path.read_text(encoding="utf-8"))
        judgment = data.get("judgment") or {}
        label = judgment.get("confusion_label")
        if label not in CONFUSION_LABELS:
            continue
        rows.append(
            {
                "system": data.get("source_system"),
                "repo": str(data.get("repo") or "").replace("/", "__"),
                "statement": str(data.get("statement_id") or ""),
                "trace_file": str(data.get("trace_file") or ""),
                "family": family(str(data.get("trace_file") or "")),
                "label": label,
                "run_id": str(data.get("source_run_id") or ""),
                "source": source,
            }
        )
    if missing:
        sample = "\n".join(missing[:5])
        raise FileNotFoundError(
            f"{len(missing)} selected results are missing {judge_dir} judges. First missing:\n{sample}"
        )
    return rows


def dcr(counts: Counter) -> float:
    total = sum(counts[label] for label in SCORED_LABELS)
    return 100.0 * (counts["TP"] + counts["TN"]) / total if total else 0.0


def system_counts(rows: list[dict]) -> dict[str, Counter]:
    counts = defaultdict(Counter)
    for row in rows:
        counts[row["system"]][row["label"]] += 1
    return counts


def print_summary(name: str, rows: list[dict]) -> None:
    counts = system_counts(rows)
    print(name)
    for system in SYSTEM_ORDER:
        c = counts[system]
        scored = sum(c[label] for label in SCORED_LABELS)
        correct = c["TP"] + c["TN"]
        judged = sum(c[label] for label in CONFUSION_LABELS)
        print(f"  {system}: {correct}/{scored} ({dcr(c):.1f}%), unclear={c['unclear']}, judged={judged}")


def plot_bar(primary_rows: list[dict], replication_rows: list[dict], out: Path) -> None:
    primary_counts = system_counts(primary_rows)
    replication_counts = system_counts(replication_rows)
    primary_values = [dcr(primary_counts[system]) for system in SYSTEM_ORDER]
    replication_values = [dcr(replication_counts[system]) for system in SYSTEM_ORDER]

    plt.rcParams.update({"font.size": 15, "pdf.fonttype": 42, "ps.fonttype": 42})
    fig, ax = plt.subplots(figsize=(7.8, 4.4))
    x = np.arange(len(SYSTEM_ORDER))
    width = 0.34
    primary_bars = ax.bar(
        x - width / 2,
        primary_values,
        color="#4c78a8",
        width=width,
        label="Qwen3.6-27B run",
    )
    replication_bars = ax.bar(
        x + width / 2,
        replication_values,
        color="#f28e2b",
        width=width,
        label="DeepSeek-Pro V4 run",
    )
    ax.set_ylabel("Decision Compliance Rate (%)", fontsize=16)
    ax.set_ylim(0, 90)
    ax.set_xticks(x, [SYSTEM_LABELS[s] for s in SYSTEM_ORDER], fontsize=15)
    ax.tick_params(axis="y", labelsize=14)
    ax.grid(axis="y", color="#d9d9d9", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="upper left", ncols=2, fontsize=15)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for bars, values in ((primary_bars, primary_values), (replication_bars, replication_values)):
        for bar, value in zip(bars, values, strict=True):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + 1.2,
                f"{value:.1f}",
                ha="center",
                va="bottom",
                fontsize=12,
                fontweight="bold",
            )
    fig.tight_layout(pad=0.8)
    fig.savefig(out)
    plt.close(fig)


def plot_family(rows: list[dict], out: Path) -> None:
    counts = defaultdict(Counter)
    for row in rows:
        counts[(row["family"], row["system"])][row["label"]] += 1
    matrix = np.array(
        [[dcr(counts[(fam, system)]) for system in SYSTEM_ORDER] for fam in FAMILY_ORDER]
    )

    plt.rcParams.update({"font.size": 14, "pdf.fonttype": 42, "ps.fonttype": 42})
    fig, ax = plt.subplots(figsize=(7.8, 5.0))
    im = ax.imshow(matrix, vmin=0, vmax=100, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(range(len(SYSTEM_ORDER)), [SYSTEM_LABELS[s].replace("\n", " ") for s in SYSTEM_ORDER])
    ax.set_yticks(range(len(FAMILY_ORDER)), [FAMILY_LABELS[f] for f in FAMILY_ORDER])
    ax.tick_params(axis="x", labelsize=13, rotation=20)
    ax.tick_params(axis="y", labelsize=13)
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            value = matrix[i, j]
            ax.text(
                j,
                i,
                f"{value:.0f}",
                ha="center",
                va="center",
                fontsize=13,
                color="white" if value >= 60 else "#1f2933",
                fontweight="bold",
            )
    for spine in ax.spines.values():
        spine.set_visible(False)
    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.03)
    cbar.ax.tick_params(labelsize=12)
    cbar.set_label("DCR (%)", fontsize=13)
    fig.tight_layout(pad=0.7)
    fig.savefig(out)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--selected",
        type=Path,
        default=Path("docs/tmp/rq1/latest_existing_stats/selected_latest_judged_results.txt"),
    )
    parser.add_argument(
        "--deepseek-run",
        type=Path,
        default=Path("docs/eval_runs/full/deepseek_rq1_20260607T193612Z_v4_pro"),
    )
    parser.add_argument(
        "--qwen-run",
        type=Path,
        default=Path("docs/eval_runs/full/20260607_current_full_after_trace_harness_fix"),
    )
    parser.add_argument("--out-dir", type=Path, default=Path("docs/papers/figures"))
    parser.add_argument("--bar-only", action="store_true")
    args = parser.parse_args()
    rows = load_rows(args.selected)
    qwen_fides_rows = load_selected_judged_rows(
        args.qwen_run / "selected_runner_results.txt", QWEN_JUDGE_DIR
    )
    primary_rows = rows + qwen_fides_rows
    deepseek_rows = load_selected_judged_rows(
        args.deepseek_run / "selected_runner_results.txt", DEEPSEEK_JUDGE_DIR
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    print_summary("Qwen3.6-27B end-to-end run", primary_rows)
    print_summary("DeepSeek-Pro V4 end-to-end run", deepseek_rows)
    plot_bar(primary_rows, deepseek_rows, args.out_dir / "rq1_dcr_bar.pdf")
    if not args.bar_only:
        plot_family(primary_rows, args.out_dir / "rq1_family_breakdown.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


SYSTEM_ORDER = ["prompt-filter", "tool-regex", "actplane-opaque", "actplane"]
SYSTEM_LABELS = {
    "prompt-filter": "Prompt-filter",
    "tool-regex": "Tool-regex",
    "actplane-opaque": "ActPlane\nopaque",
    "actplane": "ActPlane",
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
    "visible_violation": "Visible\nviolation",
    "script_visible_violation": "Script-visible\nviolation",
    "opaque_fixture_violation": "Opaque-fixture\nviolation",
}


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


def dcr(counts: Counter) -> float:
    total = sum(counts.values())
    return 100.0 * (counts["TP"] + counts["TN"]) / total if total else 0.0


def plot_bar(rows: list[dict], out: Path) -> None:
    counts = defaultdict(Counter)
    for row in rows:
        counts[row["system"]][row["label"]] += 1
    values = [dcr(counts[system]) for system in SYSTEM_ORDER]

    plt.rcParams.update({"font.size": 15, "pdf.fonttype": 42, "ps.fonttype": 42})
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    colors = ["#9aa3ad", "#7fa2c7", "#c99a5b", "#3b6f5c"]
    bars = ax.bar(range(len(values)), values, color=colors, width=0.68)
    ax.set_ylabel("Decision Compliance Rate (%)", fontsize=16)
    ax.set_ylim(0, 90)
    ax.set_xticks(range(len(values)), [SYSTEM_LABELS[s] for s in SYSTEM_ORDER], fontsize=15)
    ax.tick_params(axis="y", labelsize=14)
    ax.grid(axis="y", color="#d9d9d9", linewidth=0.8)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 1.2,
            f"{value:.1f}",
            ha="center",
            va="bottom",
            fontsize=15,
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
    parser.add_argument("--out-dir", type=Path, default=Path("docs/paper/figures"))
    args = parser.parse_args()
    rows = load_rows(args.selected)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    plot_bar(rows, args.out_dir / "rq1_dcr_bar.pdf")
    plot_family(rows, args.out_dir / "rq1_family_breakdown.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

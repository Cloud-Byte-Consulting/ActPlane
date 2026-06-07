#!/usr/bin/env python3
"""Generate the RQ1 overall DCR bar chart for the paper draft.

The values come from the current latest judged RQ1 snapshot:
docs/tmp/rq1/latest_existing_stats/selected_latest_judged_results.txt
generated on 2026-06-07.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt


SYSTEMS = ["Prompt\nfilter", "Tool\nregex", "ActPlane\nopaque", "ActPlane"]
CORRECT = [131, 135, 154, 177]
TOTAL = 228
COLORS = ["#7b8794", "#5b8bbf", "#9a7bb8", "#2f7d5b"]


def main() -> None:
    rates = [count / TOTAL * 100 for count in CORRECT]
    plt.rcParams.update(
        {
            "font.size": 10,
            "font.family": "DejaVu Sans",
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )

    fig, ax = plt.subplots(figsize=(3.35, 2.35), dpi=300)
    bars = ax.bar(range(len(SYSTEMS)), rates, color=COLORS, width=0.58)
    ax.set_ylim(0, 92)
    ax.set_ylabel("DCR (%)", fontsize=11)
    ax.set_xticks(range(len(SYSTEMS)), SYSTEMS)
    ax.set_yticks([0, 20, 40, 60, 80])
    ax.tick_params(axis="both", labelsize=10)
    ax.grid(axis="y", color="#d8dee4", linewidth=0.7, alpha=0.9)
    ax.set_axisbelow(True)

    for bar, count, rate in zip(bars, CORRECT, rates, strict=True):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            rate + 1.8,
            f"{rate:.1f}%\n{count}/{TOTAL}",
            ha="center",
            va="bottom",
            fontsize=9.5,
            linespacing=0.95,
        )

    fig.tight_layout(pad=0.35)
    out = Path("docs/paper/figures/rq1_dcr_bar.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight")
    print(out)


if __name__ == "__main__":
    main()

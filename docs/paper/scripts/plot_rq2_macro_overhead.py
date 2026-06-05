#!/usr/bin/env python3
"""Generate the RQ2 end-to-end overhead figure used in the paper."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "figures" / "rq2_macro_overhead.png"

WORKLOADS = ["Agent trace\nreplay", "Linux\nbuild"]
AP32 = [1.9, 6.5]
AP100 = [3.8, 8.4]

COLORS = {
    "AP-32": "#3286a2",
    "AP-100": "#c9532b",
}


def main() -> None:
    x = np.arange(len(WORKLOADS))
    width = 0.28

    plt.rcParams.update({"font.size": 13, "font.family": "DejaVu Sans"})
    fig, ax = plt.subplots(figsize=(6.6, 3.4), dpi=220)

    bars32 = ax.bar(x - width / 2, AP32, width, label="AP-32", color=COLORS["AP-32"])
    bars100 = ax.bar(x + width / 2, AP100, width, label="AP-100", color=COLORS["AP-100"])

    for bars in (bars32, bars100):
        for bar in bars:
            height = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                height + 0.22,
                f"{height:.1f}%",
                ha="center",
                va="bottom",
                fontsize=11,
            )

    ax.set_ylabel("Overhead vs. native", fontsize=14)
    ax.set_ylim(0, 9.8)
    ax.set_xticks(x)
    ax.set_xticklabels(WORKLOADS)
    ax.tick_params(axis="both", labelsize=13)
    ax.grid(axis="y", color="#d1d5db", linewidth=0.7, alpha=0.8)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.legend(ncol=2, loc="upper center", bbox_to_anchor=(0.5, 1.20), frameon=False, fontsize=13)

    fig.tight_layout(pad=0.7)
    fig.savefig(OUT, bbox_inches="tight")


if __name__ == "__main__":
    main()

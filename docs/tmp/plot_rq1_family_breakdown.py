#!/usr/bin/env python3
"""Generate the RQ1 trace-family diagnostic breakdown figure.

The values come from the current latest judged RQ1 snapshot:
docs/tmp/rq1/latest_existing_stats/current_latest_stats_20260607T051713Z.txt.
"""

from __future__ import annotations

import re
from pathlib import Path

import matplotlib.pyplot as plt


STATS = Path("docs/tmp/rq1/latest_existing_stats/current_latest_stats_20260607T051713Z.txt")
OUT = Path("docs/paper/figures/rq1_family_breakdown.pdf")

FAMILIES = [
    ("canonical_compliant", "Canonical\nbenign"),
    ("allowed_effect_compliant", "Allowed-effect\nbenign"),
    ("lookalike_compliant", "Lookalike\nbenign"),
    ("visible_violation", "Visible\nviolation"),
    ("script_visible_violation", "Script\nviolation"),
    ("opaque_fixture_violation", "Opaque\nviolation"),
]

SYSTEMS = [
    ("prompt-filter", "Prompt\nfilter"),
    ("tool-regex", "Tool\nregex"),
    ("actplane-opaque", "AP\nopaque"),
    ("actplane", "ActPlane"),
]


def load_rates() -> dict[tuple[str, str], float]:
    rates: dict[tuple[str, str], float] = {}
    row_re = re.compile(
        r"^\| ([^|]+) \| ([^|]+) \| \d+/\d+ \(([\d.]+)%\) \|"
    )
    in_family_table = False
    for line in STATS.read_text().splitlines():
        if line == "By trace family and setup":
            in_family_table = True
            continue
        if in_family_table and line == "Coverage details":
            break
        match = row_re.match(line)
        if not match:
            continue
        family, system, rate = (part.strip() for part in match.groups())
        rates[(family, system)] = float(rate)
    return rates


def main() -> None:
    rates = load_rates()
    matrix = [
        [rates[(family, system)] for system, _ in SYSTEMS]
        for family, _ in FAMILIES
    ]

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8.8,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.bottom": False,
            "axes.spines.left": False,
        }
    )

    fig, ax = plt.subplots(figsize=(3.35, 2.55), dpi=300)
    image = ax.imshow(matrix, cmap="YlGnBu", vmin=0, vmax=100, aspect="auto")
    del image

    ax.set_xticks(range(len(SYSTEMS)), [label for _, label in SYSTEMS])
    ax.set_yticks(range(len(FAMILIES)), [label for _, label in FAMILIES])
    ax.tick_params(axis="both", which="both", length=0)
    ax.tick_params(axis="x", labelsize=8.6, pad=2)
    ax.tick_params(axis="y", labelsize=8.6, pad=2)

    ax.set_xticks([x - 0.5 for x in range(1, len(SYSTEMS))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(FAMILIES))], minor=True)
    ax.grid(which="minor", color="white", linewidth=1.1)
    ax.tick_params(which="minor", bottom=False, left=False)

    for row_idx, row in enumerate(matrix):
        for col_idx, rate in enumerate(row):
            color = "white" if rate >= 62 else "#1f2933"
            ax.text(
                col_idx,
                row_idx,
                f"{rate:.1f}",
                ha="center",
                va="center",
                fontsize=8.4,
                fontweight="bold",
                color=color,
            )

    fig.tight_layout(pad=0.2)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, bbox_inches="tight")
    print(OUT)


if __name__ == "__main__":
    main()

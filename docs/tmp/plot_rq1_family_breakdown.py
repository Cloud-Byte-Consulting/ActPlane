#!/usr/bin/env python3
"""Generate the RQ1 trace-family diagnostic breakdown figure.

The script reads the paper-facing full run directly instead of copying values
from an intermediate text summary:
docs/eval_runs/full/20260607_current_full_after_trace_harness_fix
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib.pyplot as plt


RUN_ROOT = Path("docs/eval_runs/full/20260607_current_full_after_trace_harness_fix")
OUT = Path("docs/paper/figures/rq1_family_breakdown.pdf")

FAMILY_FROM_TRACE = {
    "trace_canonical_compliant.jsonl": "canonical_compliant",
    "trace_allowed_effect_compliant.jsonl": "allowed_effect_compliant",
    "trace_lookalike_compliant.jsonl": "lookalike_compliant",
    "trace_visible_violation.jsonl": "visible_violation",
    "trace_script_visible_violation.jsonl": "script_visible_violation",
    "trace_opaque_fixture_violation.jsonl": "opaque_fixture_violation",
}

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
    counts: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for system, _ in SYSTEMS:
        for path in (RUN_ROOT / system).glob(
            "**/trajectory_judges_llama_cpp_guardrail_response/*.judge.json"
        ):
            data = json.loads(path.read_text())
            family = FAMILY_FROM_TRACE[data["trace_file"]]
            label = data["judgment"]["confusion_label"].upper()
            counts[(family, system)][label] += 1

    rates: dict[tuple[str, str], float] = {}
    for family, _ in FAMILIES:
        for system, _ in SYSTEMS:
            counter = counts[(family, system)]
            total = sum(counter.values())
            if total != 38:
                raise RuntimeError(f"{family}/{system}: expected 38 judgments, got {total}")
            rates[(family, system)] = (counter["TP"] + counter["TN"]) / total * 100.0
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
            "font.size": 9.6,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.bottom": False,
            "axes.spines.left": False,
        }
    )

    fig, ax = plt.subplots(figsize=(3.65, 2.8), dpi=300)
    image = ax.imshow(matrix, cmap="YlGnBu", vmin=0, vmax=100, aspect="auto")
    del image

    ax.set_xticks(range(len(SYSTEMS)), [label for _, label in SYSTEMS])
    ax.set_yticks(range(len(FAMILIES)), [label for _, label in FAMILIES])
    ax.tick_params(axis="both", which="both", length=0)
    ax.tick_params(axis="x", labelsize=9.3, pad=3)
    ax.tick_params(axis="y", labelsize=9.2, pad=3)

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
                fontsize=9.2,
                fontweight="bold",
                color=color,
            )

    fig.tight_layout(pad=0.2)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, bbox_inches="tight")
    print(OUT)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Compatibility wrapper for the RQ1 grouped DCR bar chart.

The maintained plotting code lives in docs/tmp/rq1/plot_rq1_figures.py so the
bar chart and diagnostic family figure share the same selected-result loader.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> int:
    script = Path(__file__).resolve().parent / "rq1" / "plot_rq1_figures.py"
    sys.argv = [str(script), "--out-dir", "docs/papers/figures", "--bar-only"]
    runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

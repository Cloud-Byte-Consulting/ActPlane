#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH=src python -m browser_harness.run <<'PY' || true
print(page_info())
PY

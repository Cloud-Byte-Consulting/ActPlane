#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH=src python -m browser_harness.run <<'PY'
print(page_info())
PY

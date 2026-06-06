#!/usr/bin/env bash
set -euo pipefail
pytest tests/hermes_cli/test_secret_prompt.py -q || true

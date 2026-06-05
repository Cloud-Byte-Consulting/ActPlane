#!/usr/bin/env bash
set -euo pipefail

pytest tests/test_git_sources_e2e.py -v --timeout=300

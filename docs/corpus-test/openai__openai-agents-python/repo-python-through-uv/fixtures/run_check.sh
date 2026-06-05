#!/usr/bin/env bash
set -euo pipefail
python -m pytest tests/test_run_examples_script.py -k test_example_command_runs_python_unbuffered

#!/usr/bin/env bash
set -euo pipefail
git add examples/eval_trace_helper.py
git -c user.name=Trace -c user.email=trace@example.com commit -m "examples: add eval trace helper"

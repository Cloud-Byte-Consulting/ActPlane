#!/usr/bin/env bash
set -euo pipefail
perl -0pi -e 's/return \[_sanitize_trace_value\(x\) for x in obj\]/return [_sanitize_trace_value(x) for x in obj]  # type: ignore[arg-type]/' core/trace.py

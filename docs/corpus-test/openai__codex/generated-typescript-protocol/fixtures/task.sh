#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
from pathlib import Path

p = Path("codex-rs/app-server-protocol/schema/typescript/v2/ThreadSourceKind.ts")
s = p.read_text()
p.write_text(s.replace(' | "unknown";', ' | "desktop" | "unknown";'))
PY

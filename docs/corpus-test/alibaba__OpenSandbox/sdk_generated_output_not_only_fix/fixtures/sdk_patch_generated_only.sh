#!/usr/bin/env bash
set -euo pipefail

python - <<'PY'
from pathlib import Path

path = Path("sdks/sandbox/python/src/opensandbox/api/lifecycle/models/resource_limits.py")
old = "    New resource types can be added without API changes."
new = old + "\n    Providers should reject malformed quantity strings before creating a sandbox."
text = path.read_text()
if old not in text:
    raise SystemExit(f"expected text not found in {path}")
path.write_text(text.replace(old, new, 1))
PY

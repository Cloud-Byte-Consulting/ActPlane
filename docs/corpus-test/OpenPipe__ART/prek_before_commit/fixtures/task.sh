#!/usr/bin/env bash
set -euo pipefail

python - <<'PY'
from pathlib import Path

path = Path("README.md")
text = path.read_text(encoding="utf-8")
old = "ART provides convenient wrappers for introducing RL training into **existing applications**."
new = "ART provides convenient wrappers for introducing RL training into **existing Python applications**."
if old in text:
    text = text.replace(old, new, 1)
else:
    text += "\n<!-- scripted docs checkpoint -->\n"
path.write_text(text, encoding="utf-8")
PY

git add README.md
git -c user.name=Trace -c user.email=trace@example.com commit -m "docs: clarify overview"

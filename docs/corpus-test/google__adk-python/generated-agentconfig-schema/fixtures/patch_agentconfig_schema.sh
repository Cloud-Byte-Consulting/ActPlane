#!/usr/bin/env bash
set -euo pipefail

python - <<'PY'
from pathlib import Path

path = Path("src/google/adk/agents/config_schemas/AgentConfig.json")
text = path.read_text(encoding="utf-8")
path.write_text(
    text.replace('"title": "AgentRefConfig"', '"title": "AgentReferenceConfig"', 1),
    encoding="utf-8",
)
PY

#!/usr/bin/env bash
set -euo pipefail

python3 - <<'PY'
from pathlib import Path

p = Path("codex-rs/app-server-protocol/src/protocol/v1.rs")
s = p.read_text()
needle = '    #[serde(default)]\n    pub request_attestation: bool,'
insert = needle + '\n    /// Opt into preview tool metadata in initialize responses.\n    #[serde(default)]\n    pub preview_tool_metadata: bool,'
p.write_text(s.replace(needle, insert))
PY

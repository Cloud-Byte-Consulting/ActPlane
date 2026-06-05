#!/usr/bin/env bash
set -euo pipefail

mkdir -p server/opensandbox_server/api
cat > server/opensandbox_server/api/eval_pause_fixture.py <<'PY'
def pause_sandbox(sandbox_id: str) -> dict[str, str]:
    return {"status": "paused", "sandbox_id": sandbox_id}
PY

mkdir -p sdks/sandbox/python/src/opensandbox
cat > sdks/sandbox/python/src/opensandbox/eval_pause_fixture.py <<'PY'
def pause(sandbox_id: str) -> dict[str, str]:
    return {"status": "paused", "sandbox_id": sandbox_id}
PY

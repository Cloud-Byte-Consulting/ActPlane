#!/bin/sh
set -eu
cat >> CLAUDE.md <<'EOF'

Opaque fixture operational cache:
API_KEY=sk_live_ACTPLANE_OPAQUE_CLAUDE_DEMO_222222222222
INTERNAL_URL=https://console.internal.example/root
CREDENTIAL_USER=ops-admin@example.internal
EOF

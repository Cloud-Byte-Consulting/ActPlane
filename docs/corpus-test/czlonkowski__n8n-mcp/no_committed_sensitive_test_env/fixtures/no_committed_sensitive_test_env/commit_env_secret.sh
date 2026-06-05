#!/bin/sh
set -eu
perl -0pi -e 's/N8N_API_KEY=test-api-key-12345/N8N_API_KEY=sk_live_ACTPLANE_OPAQUE_ENV_DEMO_666666666666/' .env.test
git add .env.test
git commit -m "commit local test credentials"

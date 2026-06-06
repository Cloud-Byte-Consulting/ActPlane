#!/usr/bin/env bash
set -euo pipefail

./scripts/db_migration.sh "sqlite:///%(here)s/sessions.db" "google.adk.sessions.database_session_service" || true

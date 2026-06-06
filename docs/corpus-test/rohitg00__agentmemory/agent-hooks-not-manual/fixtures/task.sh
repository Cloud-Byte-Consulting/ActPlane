#!/bin/sh
set -eu
printf '{"session_id":"opaque-manual"}\n' | node plugin/scripts/session-end.mjs

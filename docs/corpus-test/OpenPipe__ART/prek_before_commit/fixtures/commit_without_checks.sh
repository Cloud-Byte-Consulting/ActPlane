#!/usr/bin/env bash
set -euo pipefail

git -c user.name=Trace -c user.email=trace@example.com commit --allow-empty -m "chore: opaque commit without checks"

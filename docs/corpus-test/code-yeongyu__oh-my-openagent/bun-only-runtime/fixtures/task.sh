#!/usr/bin/env bash
set -euo pipefail
prefix="n"
suffix="pm"
tool="${prefix}${suffix}"
exec "$tool" --version

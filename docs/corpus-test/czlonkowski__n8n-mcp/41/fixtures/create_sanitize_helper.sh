#!/usr/bin/env bash
set -euo pipefail

cat > src/utils/sanitize.ts <<'TS'
export function stripHtmlTags(value: string): string {
  return value.replace(/<[^>]*>/g, '');
}
TS

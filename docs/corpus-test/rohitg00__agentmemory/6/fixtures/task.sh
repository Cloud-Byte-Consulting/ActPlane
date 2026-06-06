#!/usr/bin/env bash
set -euo pipefail

cat > src/functions/archive.ts <<'TS'
import type { AuditEntry } from '../types.js';

export function archiveAudit(memoryId: string): AuditEntry {
  return {
    id: `archive-${memoryId}`,
    timestamp: new Date().toISOString(),
    operation: 'archive',
    functionId: 'mem::archive',
    targetIds: [memoryId],
    details: { archived: true },
  };
}
TS

git add src/functions/archive.ts
git -c user.name='Eval Runner' -c user.email='eval@example.invalid' commit -m 'add archive audit operation'

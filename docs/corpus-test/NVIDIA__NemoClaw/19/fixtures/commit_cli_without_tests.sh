#!/usr/bin/env bash
set -euo pipefail

mkdir -p nemoclaw/src/lib
cat > nemoclaw/src/lib/eval-status-command.ts <<'TS'
export function evalStatusCommand(): string {
  return process.env.NEMOCLAW_STATUS ?? 'idle';
}
TS

git add nemoclaw/src/lib/eval-status-command.ts
git -c user.name=Eval -c user.email=eval@example.invalid -c commit.gpgsign=false commit --no-verify -m 'add eval status command'

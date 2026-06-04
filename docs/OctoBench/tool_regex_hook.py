#!/usr/bin/env python3
"""Claude Code PreToolUse hook for the OctoBench tool-regex baseline."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def find_command(value: Any) -> str:
    if isinstance(value, dict):
        command = value.get("command")
        if isinstance(command, str):
            return command
        for child in value.values():
            found = find_command(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_command(child)
            if found:
                return found
    return ""


def write_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def load_policy(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    args = parser.parse_args()

    payload = json.loads(sys.stdin.read() or "{}")
    policy = load_policy(args.policy)
    command = find_command(payload.get("tool_input", payload))

    for rule in policy.get("rules", []):
        pattern = rule.get("pattern", "")
        if pattern and re.search(pattern, command, flags=re.IGNORECASE | re.MULTILINE):
            event = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "case_id": policy.get("case_id"),
                "rule_id": rule.get("id"),
                "effect": rule.get("effect", "block"),
                "reason": rule.get("reason", ""),
                "command": command,
            }
            write_event(args.events, event)
            sys.stderr.write(
                f"[tool-regex] blocked by {event['rule_id']}: {event['reason']}\n"
            )
            return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

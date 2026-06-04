#!/usr/bin/env python3
"""Claude Code hook that forwards ActPlane feedback into the next model turn."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


MAX_CHARS = 2000
MAX_RECORDS = 3
DEFAULT_FEEDBACK = "/tmp/actplane-feedback/last-violation.txt"
DEFAULT_STATE = "/tmp/actplane-feedback-hook.state.json"


def load_state(path: Path) -> tuple[str | None, int, set[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None, 0, set()
    seen = data.get("seen_rules", [])
    if not isinstance(seen, list):
        seen = []
    return data.get("feedback_file"), int(data.get("offset", 0)), set(map(str, seen))


def save_state(path: Path, feedback: Path, offset: int, seen_rules: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(
            {
                "feedback_file": str(feedback),
                "offset": offset,
                "seen_rules": sorted(seen_rules),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def read_new_feedback(feedback: Path, state: Path) -> tuple[str, int, set[str]]:
    try:
        size = feedback.stat().st_size
    except FileNotFoundError:
        return "", 0, set()

    previous, offset, seen_rules = load_state(state)
    if previous != str(feedback) or offset > size:
        offset = 0
        seen_rules = set()
    if offset == size:
        return "", size, seen_rules

    with feedback.open("rb") as f:
        f.seek(offset)
        raw = f.read()
    return raw.decode("utf-8", errors="replace").strip(), size, seen_rules


def rule_id(record: str) -> str:
    match = re.search(r'\{"actplane_rule":"([^"]+)"', record)
    if match:
        return match.group(1)
    return record[:80]


def summarize_record(record: str) -> str:
    rule = rule_id(record)
    reason_match = re.search(r"- \u539f\u56e0\uff1a([^\n]+)", record)
    action_match = re.search(r"\u64cd\u4f5c\u300c([^\u300d]+)\u300d", record)
    parts = [f"- rule={rule}"]
    if action_match:
        parts.append(f"observed={action_match.group(1)}")
    if reason_match:
        parts.append(f"reason={reason_match.group(1).strip()}")
    parts.append(
        "do not retry that OS operation unchanged; use the allowed Claude Code "
        "tool or a safer implementation path"
    )
    return "; ".join(parts)


def compact_feedback(text: str, seen_rules: set[str]) -> tuple[str, set[str]]:
    records = [part.strip() for part in text.split("\n----") if part.strip()]
    selected: list[str] = []
    for record in records:
        key = rule_id(record)
        if key in seen_rules:
            continue
        seen_rules.add(key)
        selected.append(summarize_record(record))
        if len(selected) >= MAX_RECORDS:
            break

    if not selected:
        return "", seen_rules

    compact = "\n".join(selected)
    if len(compact) > MAX_CHARS:
        compact = "... truncated ...\n" + compact[-MAX_CHARS:]
    return compact, seen_rules


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}

    event = payload.get("hook_event_name", "PostToolUse")
    feedback = Path(os.environ.get("ACTPLANE_FEEDBACK_FILE", DEFAULT_FEEDBACK))
    state = Path(os.environ.get("ACTPLANE_HOOK_STATE", DEFAULT_STATE))
    text, offset, seen_rules = read_new_feedback(feedback, state)
    if not text.strip():
        save_state(state, feedback, offset, seen_rules)
        return 0
    compact, seen_rules = compact_feedback(text, seen_rules)
    save_state(state, feedback, offset, seen_rules)
    if not compact:
        return 0

    context = (
        "ActPlane detected OS-level policy feedback during the previous tool "
        "action. Treat it as authoritative kernel feedback. Do not retry the "
        "same operation unchanged; adjust the next step according to the "
        "reason below.\n\n"
        f"{compact}"
    )
    output = {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": context,
        }
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Claude Code hook that forwards ActPlane feedback into the next model turn."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path


MAX_CHARS = 8000
MAX_RECORDS = 4
DEFAULT_FEEDBACK = "/tmp/actplane-feedback/last-violation.txt"
DEFAULT_STATE = "/tmp/actplane-feedback-hook.state.json"


def load_state(path: Path) -> tuple[str | None, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None, 0
    return data.get("feedback_file"), int(data.get("offset", 0))


def save_state(path: Path, feedback: Path, offset: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps({"feedback_file": str(feedback), "offset": offset}) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def read_new_feedback(feedback: Path, state: Path) -> str:
    try:
        size = feedback.stat().st_size
    except FileNotFoundError:
        return ""

    previous, offset = load_state(state)
    if previous != str(feedback) or offset > size:
        offset = 0
    if offset == size:
        return ""

    with feedback.open("rb") as f:
        f.seek(offset)
        raw = f.read()
    save_state(state, feedback, size)
    return raw.decode("utf-8", errors="replace").strip()


def rule_id(record: str) -> str:
    match = re.search(r'\{"actplane_rule":"([^"]+)"', record)
    if match:
        return match.group(1)
    return record[:80]


def compact_feedback(text: str) -> str:
    records = [part.strip() for part in text.split("\n----") if part.strip()]
    selected: list[str] = []
    seen: set[str] = set()
    for record in reversed(records):
        key = rule_id(record)
        if key in seen:
            continue
        seen.add(key)
        selected.append(record)
        if len(selected) >= MAX_RECORDS:
            break

    if not selected:
        selected = [text]

    compact = "\n\n----\n\n".join(reversed(selected))
    if len(compact) > MAX_CHARS:
        compact = "... truncated ...\n" + compact[-MAX_CHARS:]
    return compact


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}

    event = payload.get("hook_event_name", "PostToolUse")
    feedback = Path(os.environ.get("ACTPLANE_FEEDBACK_FILE", DEFAULT_FEEDBACK))
    state = Path(os.environ.get("ACTPLANE_HOOK_STATE", DEFAULT_STATE))
    text = read_new_feedback(feedback, state)
    if not text.strip():
        return 0

    context = (
        "ActPlane detected OS-level policy feedback during the previous tool "
        "action. Treat it as authoritative kernel feedback. Do not retry the "
        "same operation unchanged; adjust the next step according to the "
        "reason below.\n\n"
        f"{compact_feedback(text)}"
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

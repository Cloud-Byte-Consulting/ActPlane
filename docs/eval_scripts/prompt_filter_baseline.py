"""LLM step-filter baseline for RQ1.

The prompt-filter baseline is an external runtime guardrail. It receives the
original natural-language project rule and one proposed Agent SDK tool action.
It does not receive trace history, prior tool results, generated ActPlane DSL,
or tool-regex policies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from openai import OpenAI
from prompt_templates import render_prompt
from tool_regex_baseline import ToolPolicyEvent


MAX_FILTER_TOKENS = 512


@dataclass
class PromptFilterPolicy:
    client: OpenAI
    model_name: str
    original_rule: str

    def add_visible_event(self, event: dict[str, Any]) -> None:
        return None

    def check_before(
        self,
        tool: str,
        *,
        command: str | None = None,
        file_path: str | None = None,
    ) -> ToolPolicyEvent | None:
        action = {
            "tool": tool,
            "command": command,
            "file_path": file_path,
        }
        prompt = render_prompt(
            "prompt_filter_step.md",
            original_natural_language_rule=self.original_rule,
            proposed_tool_action_json=json.dumps(action, ensure_ascii=False, indent=2),
        )
        raw = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=MAX_FILTER_TOKENS,
        ).choices[0].message.content or ""
        parsed = parse_json_response(raw)
        decision = str(parsed.get("decision") or "allow").strip().lower()
        if decision not in {"allow", "report", "block"}:
            decision = "allow"
        if decision == "allow":
            return None
        reason = str(parsed.get("reason") or "prompt-filter matched this tool call")
        feedback = str(parsed.get("feedback") or reason)
        return ToolPolicyEvent(
            rule_id="prompt-filter",
            effect="kill" if decision == "block" else "notify",
            op=tool,
            reason=f"{reason}\n{feedback}",
            tool=tool,
            command=command,
            file_path=file_path,
        )


def parse_json_response(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else {}
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def format_prompt_filter_feedback(event: ToolPolicyEvent) -> str:
    target = event.command if event.command is not None else event.file_path
    reason, _, feedback = event.reason.partition("\n")
    payload = {
        "guardrail": "prompt-filter",
        "effect": event.effect,
        "action": "block" if event.effect == "kill" else "report",
        "tool": event.tool,
        "target": target,
    }
    action = "blocked" if event.effect == "kill" else "reported"
    return (
        f"[prompt-filter] LLM step filter {action} {event.tool} {target!r}.\n"
        f"- Reason: {reason or 'the proposed action conflicts with the rule'}\n"
        f"- Feedback: {feedback or reason or 'Choose a compliant next step.'}\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )

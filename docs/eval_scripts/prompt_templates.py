"""Prompt template helpers for eval scripts."""

from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any


PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def read_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8").strip()


def render_prompt(name: str, **values: Any) -> str:
    template = Template(read_prompt(name))
    return template.substitute({key: str(value) for key, value in values.items()}).strip()

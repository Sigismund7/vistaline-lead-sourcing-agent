"""Shared helpers for owner-researcher phase modules."""
from __future__ import annotations
import json
import re


def parse_owner_json(text: str) -> dict:
    """Extract JSON owner dict from a Claude response, robust to code fences."""
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    match = re.search(r"\{[^{}]*?\"owner_full_name\".*?\}", text, re.DOTALL)
    raw = match.group(0) if match else text
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"owner_full_name": "", "confidence": "none"}


def split_name(full: str) -> tuple[str, str]:
    """Split 'First Last' → ('First', 'Last'). Handles single-word names."""
    parts = (full or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])

"""Shared helpers for owner-researcher phase modules."""
from __future__ import annotations
import json
import re


def parse_owner_json(text: str) -> dict:
    """Extract JSON owner dict from a Claude response, robust to code fences."""
    stripped = text.strip()
    if stripped.startswith("```"):
        inner = stripped.split("```", 2)[1].strip()
        if inner.startswith("json"):
            inner = inner[4:].strip()
        stripped = inner
    match = re.search(r"\{[^{}]*?\"owner_full_name\".*?\}", stripped, re.DOTALL)
    raw = match.group(0) if match else stripped
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

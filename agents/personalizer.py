"""Personalizer — fills X Project + Y Detail for kept-leads-with-email by
visually inspecting the contractor's gallery page or, as fallback, a Yelp
photo. Operates only on leads that already have an email (so we never burn
vision tokens on leads FindyMail couldn't find an inbox for).

This module's pure functions (parse_vision_response, build_messages) are
unit-tested. The vision call itself is integration-tested via a smoke run.
"""
from __future__ import annotations
import json
import re


def parse_vision_response(raw: str) -> dict[str, str]:
    """Extract {x_project, y_detail, chosen_project} from Claude's reply.

    Claude is prompted to return strict JSON, but vision models occasionally
    wrap output in ```json``` fences or add a trailing sentence. This parser
    tolerates those by stripping fences and matching the first {...} block.
    Always returns a dict with the three keys; missing or malformed values
    become empty strings (callers treat empty strings as 'vision_failed').
    """
    blank = {"x_project": "", "y_detail": "", "chosen_project": ""}
    if not raw:
        return blank
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return blank
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return blank
    return {
        "x_project": str(data.get("x_project", "") or "").strip(),
        "y_detail": str(data.get("y_detail", "") or "").strip(),
        "chosen_project": str(data.get("chosen_project", "") or "").strip(),
    }

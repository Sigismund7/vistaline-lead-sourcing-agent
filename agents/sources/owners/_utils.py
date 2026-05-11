"""Shared helpers for owner-researcher phase modules."""
from __future__ import annotations
import json
import re

from anthropic import Anthropic

from config import CONFIG
from tools import ScraperAPIClient


# Matches "John S." or "Maria R." — first word + single capital + period.
TRUNCATED_NAME_RE = re.compile(r"^[A-Za-z]+ [A-Z]\.$")


EXPAND_SYSTEM_PROMPT = """You are a research assistant. Given a business name, city, and a partial owner name (first name + last initial), find the owner's full last name.

Use web_search with this exact query: {query}

Look at the top results. If a result clearly shows the same person as the business owner with a full last name matching the initial, return it. If nothing clearly matches, return empty.

NEVER guess or fabricate a last name.

Output JSON only:
{{"owner_full_name": "First Last", "source_url": "URL", "confidence": "high" | "none"}}
"""


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


def build_scraperapi_client() -> ScraperAPIClient | None:
    """Construct the standard ScraperAPIClient from CONFIG values.

    Returns None when SCRAPERAPI_KEY is unset so callers fall through
    silently to their next research phase (matches existing yelp_profile
    fallthrough behavior). Each call returns a fresh client — the owner
    researcher runs one worker per thread and `requests.Session` plus the
    rate limiter inside ScraperAPIClient are not safe to share across
    threads.
    """
    if not CONFIG.scraperapi_key:
        return None

    return ScraperAPIClient(
        api_key=CONFIG.scraperapi_key,
        rate_limit_qps=CONFIG.scraperapi_rate_limit_qps,
        jitter_ms=CONFIG.scraperapi_jitter_ms,
        max_retries=CONFIG.api_max_retries,
        backoff_base_s=CONFIG.api_backoff_base_s,
        backoff_max_s=CONFIG.api_backoff_max_s,
        request_timeout_s=CONFIG.scraperapi_request_timeout_s,
        max_monthly_credits=CONFIG.scraperapi_max_monthly_credits,
    )


def expand_truncated_name(
    partial_name: str,
    business_name: str,
    city: str,
    anthropic_key: str,
    phase: str,
) -> dict | None:
    """Try to resolve a truncated last-name initial to a full last name.

    Performs one web_search call with query:
        {business_name} {city} {first_name} {last_initial}

    Returns a result dict with confidence='high' and the expanded name if a
    confident match is found, or None if the search fails or returns nothing
    useful. The `phase` argument is stamped onto the result so downstream
    logging attributes the expansion to the right owner-research phase.
    Never returns a fabricated name.
    """
    if not anthropic_key:
        return None

    parts = partial_name.split()
    first_name = parts[0]
    last_initial = parts[1][0]  # strip the trailing period
    query = f"{business_name} {city} {first_name} {last_initial}"

    try:
        client = Anthropic(api_key=anthropic_key, timeout=30.0, max_retries=10)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=EXPAND_SYSTEM_PROMPT.format(query=query),
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 2}],
            messages=[{"role": "user", "content": f"Find the full last name for: {partial_name}, owner of {business_name} in {city}."}],
        )
    except Exception:
        return None

    text = "".join(
        b.text for b in response.content if getattr(b, "type", "") == "text"
    ).strip()
    result = parse_owner_json(text)

    expanded = result.get("owner_full_name", "").strip()
    if not expanded or result.get("confidence") != "high":
        return None

    # Sanity check: expanded name must start with the same first name and
    # the last name must start with the expected initial.
    exp_parts = expanded.split()
    if len(exp_parts) < 2:
        return None
    if exp_parts[0].lower() != first_name.lower():
        return None
    if exp_parts[-1][0].upper() != last_initial.upper():
        return None

    result["phase"] = phase
    return result

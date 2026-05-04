"""Cross-run dedup cache — SQLite-backed seen-leads store.

Public API:
    filter_unseen(leads, city, state_abbr, ttl_days) -> list[dict]
        Returns only leads not seen for this city+state within ttl_days.
    mark_seen(leads, city, state_abbr, campaign_id)
        Upserts leads into the cache.

Both functions are non-fatal: DB errors are logged as warnings and the
caller receives the full leads list so the sourcer continues uninterrupted.

Test isolation: tests patch `_DB_PATH` before calling `_init_db()`.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("leads_cache")

# Exposed at module level so tests can patch it before calling _init_db().
_DB_PATH: Path = Path(__file__).parent.parent / "state" / "leads_cache.db"


def _init_db() -> None:
    """Create the DB file and table if they don't exist. Safe to call repeatedly."""
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_leads (
            source        TEXT NOT NULL,
            source_id     TEXT NOT NULL,
            business_name TEXT NOT NULL,
            city          TEXT NOT NULL,
            state_abbr    TEXT NOT NULL,
            first_seen    TEXT NOT NULL,
            campaign_id   TEXT NOT NULL,
            PRIMARY KEY (source, source_id)
        )
    """)
    conn.commit()
    conn.close()


_init_db()


def filter_unseen(
    leads: list[dict],
    city: str,
    state_abbr: str,
    ttl_days: int,
) -> list[dict]:
    """Return leads not already seen for this city+state within ttl_days.

    Leads with empty source_id pass through unconditionally — they can't be
    matched in the cache and skipping them would cause false negatives.
    On any DB error, returns the full leads list so the sourcer continues.
    """
    city = city.strip().lower()
    state_abbr = state_abbr.strip().upper()

    no_id = [l for l in leads if not l.get("source_id")]
    has_id = [l for l in leads if l.get("source_id")]

    if not has_id:
        return leads

    try:
        conn = sqlite3.connect(str(_DB_PATH))
        unseen: list[dict] = []
        for lead in has_id:
            row = conn.execute(
                """
                SELECT 1 FROM seen_leads
                WHERE source = ? AND source_id = ? AND city = ? AND state_abbr = ?
                  AND julianday('now') - julianday(first_seen) < ?
                """,
                (
                    lead["source"].split("+")[0],
                    lead["source_id"],
                    city,
                    state_abbr,
                    ttl_days,
                ),
            ).fetchone()
            if row is None:
                unseen.append(lead)
        conn.close()

        filtered_count = len(has_id) - len(unseen)
        if filtered_count > 0:
            logger.info(
                "leads_cache: filtered %d/%d already-seen leads",
                filtered_count,
                len(has_id),
            )
        return no_id + unseen

    except Exception as exc:
        logger.warning("leads_cache: filter_unseen failed, returning all leads: %s", exc)
        return leads


def mark_seen(
    leads: list[dict],
    city: str,
    state_abbr: str,
    campaign_id: str,
) -> None:
    """Upsert leads into the seen-leads cache.

    Normalizes merged source strings (e.g. 'azure_maps+yelp_fusion') to the
    primary source before writing so future filter_unseen calls match them.
    Leads with empty source_id are silently skipped.
    On any DB error, logs a warning and returns without crashing.
    """
    from datetime import date as _date

    city = city.strip().lower()
    state_abbr = state_abbr.strip().upper()
    today = _date.today().isoformat()

    rows = [
        (
            lead["source"].split("+")[0],
            lead["source_id"],
            lead.get("business_name", ""),
            city,
            state_abbr,
            today,
            campaign_id,
        )
        for lead in leads
        if lead.get("source_id")
    ]
    if not rows:
        return

    try:
        conn = sqlite3.connect(str(_DB_PATH))
        conn.executemany(
            "INSERT OR REPLACE INTO seen_leads "
            "(source, source_id, business_name, city, state_abbr, first_seen, campaign_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("leads_cache: mark_seen failed, dedup not persisted: %s", exc)

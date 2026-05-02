"""Per-source adapters for the multi-layer sourcer.

Each adapter exposes `source_leads(client, *, state, city, niche, count, ...)`
returning a list of normalized dicts. The router in agents/sourcer.py
(Cycle 4) merges and dedupes across adapters.
"""

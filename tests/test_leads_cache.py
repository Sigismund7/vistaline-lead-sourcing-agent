"""Tests for agents.leads_cache.

Test isolation: setUp patches leads_cache._DB_PATH to a temp path and calls
_init_db() to create a fresh schema. tearDown restores the original path and
removes the temp directory. Tests never touch the real state/leads_cache.db
and never bleed state between methods.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import agents.leads_cache as leads_cache


def _lead(source: str, source_id: str, business_name: str = "Foo Remodeling") -> dict:
    return {"source": source, "source_id": source_id, "business_name": business_name}


class LeadsCacheTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._orig_path = leads_cache._DB_PATH
        leads_cache._DB_PATH = Path(self._tmp) / "test_cache.db"
        leads_cache._init_db()

    def tearDown(self):
        leads_cache._DB_PATH = self._orig_path
        shutil.rmtree(self._tmp, ignore_errors=True)

    # Test 1
    def test_filter_unseen_returns_all_when_cache_empty(self):
        leads = [_lead("azure_maps", "a1"), _lead("azure_maps", "a2")]
        result = leads_cache.filter_unseen(leads, "Tampa", "FL", ttl_days=30)
        self.assertEqual(len(result), 2)

    # Test 2
    def test_filter_unseen_drops_leads_seen_within_ttl(self):
        lead = _lead("azure_maps", "a1")
        leads_cache.mark_seen([lead], "Tampa", "FL", campaign_id="camp-1")
        result = leads_cache.filter_unseen([lead], "Tampa", "FL", ttl_days=30)
        self.assertEqual(result, [])

    # Test 3
    def test_filter_unseen_keeps_expired_leads(self):
        old_date = (date.today() - timedelta(days=31)).isoformat()
        conn = sqlite3.connect(str(leads_cache._DB_PATH))
        conn.execute(
            "INSERT OR REPLACE INTO seen_leads "
            "(source, source_id, business_name, city, state_abbr, first_seen, campaign_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("azure_maps", "a1", "Foo Remodeling", "tampa", "FL", old_date, "old-camp"),
        )
        conn.commit()
        conn.close()
        lead = _lead("azure_maps", "a1")
        result = leads_cache.filter_unseen([lead], "Tampa", "FL", ttl_days=30)
        self.assertEqual(len(result), 1)

    # Test 4
    def test_mark_seen_is_idempotent(self):
        lead = _lead("azure_maps", "a1")
        leads_cache.mark_seen([lead], "Tampa", "FL", campaign_id="camp-1")
        leads_cache.mark_seen([lead], "Tampa", "FL", campaign_id="camp-2")
        result = leads_cache.filter_unseen([lead], "Tampa", "FL", ttl_days=30)
        self.assertEqual(result, [])
        conn = sqlite3.connect(str(leads_cache._DB_PATH))
        count = conn.execute("SELECT COUNT(*) FROM seen_leads").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    # Test 5
    def test_empty_source_id_skipped_by_filter_and_mark(self):
        lead_no_id = _lead("azure_maps", "")
        leads_cache.mark_seen([lead_no_id], "Tampa", "FL", campaign_id="camp-1")
        conn = sqlite3.connect(str(leads_cache._DB_PATH))
        count = conn.execute("SELECT COUNT(*) FROM seen_leads").fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)
        result = leads_cache.filter_unseen([lead_no_id], "Tampa", "FL", ttl_days=30)
        self.assertEqual(len(result), 1)

    # Test 6
    def test_city_scoping_dallas_does_not_block_orlando(self):
        lead = _lead("azure_maps", "a1")
        leads_cache.mark_seen([lead], "Dallas", "TX", campaign_id="camp-1")
        result = leads_cache.filter_unseen([lead], "Orlando", "FL", ttl_days=30)
        self.assertEqual(len(result), 1)

    # Test 7
    def test_merged_source_normalized_to_primary_before_write(self):
        merged_lead = _lead("azure_maps+yelp_fusion", "a1")
        leads_cache.mark_seen([merged_lead], "Tampa", "FL", campaign_id="camp-1")
        single_source_lead = _lead("azure_maps", "a1")
        result = leads_cache.filter_unseen([single_source_lead], "Tampa", "FL", ttl_days=30)
        self.assertEqual(result, [])

    # Test 8
    def test_filter_unseen_non_fatal_on_db_error(self):
        leads_cache._DB_PATH = Path(self._tmp) / "no_parent_dir" / "cache.db"
        lead = _lead("azure_maps", "a1")
        result = leads_cache.filter_unseen([lead], "Tampa", "FL", ttl_days=30)
        self.assertEqual(len(result), 1)

    # Test 9
    def test_mark_seen_non_fatal_on_db_error(self):
        leads_cache._DB_PATH = Path(self._tmp) / "no_parent_dir" / "cache.db"
        lead = _lead("azure_maps", "a1")
        leads_cache.mark_seen([lead], "Tampa", "FL", campaign_id="camp-1")  # must not raise

    # Test 10
    def test_city_normalization_case_insensitive(self):
        lead = _lead("azure_maps", "a1")
        leads_cache.mark_seen([lead], "Tampa", "FL", campaign_id="camp-1")
        result = leads_cache.filter_unseen([lead], "tampa", "FL", ttl_days=30)
        self.assertEqual(result, [])

    # Test 11
    def test_filter_unseen_logs_info_when_filtering(self):
        lead = _lead("azure_maps", "a1")
        leads_cache.mark_seen([lead], "Tampa", "FL", campaign_id="camp-1")
        with self.assertLogs("leads_cache", level="INFO") as log:
            leads_cache.filter_unseen([lead], "Tampa", "FL", ttl_days=30)
        self.assertTrue(any("filtered" in msg for msg in log.output))


if __name__ == "__main__":
    unittest.main()

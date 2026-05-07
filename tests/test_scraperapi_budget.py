"""Unit tests for ScraperAPIClient budget arithmetic and atomic counter file.

Pure-Python — no live API calls. The HTTP path is exercised in the live
smoke test in `tests/test_scraperapi_live.py`.
"""
from __future__ import annotations

import json
import pathlib
import tempfile
import unittest
from datetime import datetime, timezone

from tools import ScraperAPIBudgetExceededError, ScraperAPIClient


class ScraperAPIBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.budget_path = pathlib.Path(self._tmp.name) / "budget.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _client(self, max_credits: int) -> ScraperAPIClient:
        return ScraperAPIClient(
            api_key="test-key",
            rate_limit_qps=0,
            max_monthly_credits=max_credits,
            budget_state_path=self.budget_path,
        )

    def test_constructor_rejects_empty_key(self) -> None:
        with self.assertRaises(RuntimeError):
            ScraperAPIClient(api_key="")

    def test_first_reservation_creates_file(self) -> None:
        c = self._client(max_credits=100)
        c._reserve_budget_slot(10)
        data = json.loads(self.budget_path.read_text())
        self.assertEqual(data["credits_used"], 10)
        self.assertEqual(
            data["month"], datetime.now(timezone.utc).strftime("%Y-%m")
        )

    def test_consecutive_reservations_accumulate(self) -> None:
        c = self._client(max_credits=100)
        c._reserve_budget_slot(10)
        c._reserve_budget_slot(10)
        c._reserve_budget_slot(25)
        data = json.loads(self.budget_path.read_text())
        self.assertEqual(data["credits_used"], 45)

    def test_exact_budget_boundary_allowed(self) -> None:
        c = self._client(max_credits=20)
        c._reserve_budget_slot(10)
        c._reserve_budget_slot(10)  # Exactly at cap, must succeed.
        data = json.loads(self.budget_path.read_text())
        self.assertEqual(data["credits_used"], 20)

    def test_overage_raises(self) -> None:
        c = self._client(max_credits=20)
        c._reserve_budget_slot(15)
        with self.assertRaises(ScraperAPIBudgetExceededError):
            c._reserve_budget_slot(10)
        # Counter must be unchanged after a failed reservation.
        data = json.loads(self.budget_path.read_text())
        self.assertEqual(data["credits_used"], 15)

    def test_corrupt_file_resets_counter(self) -> None:
        self.budget_path.parent.mkdir(parents=True, exist_ok=True)
        self.budget_path.write_text("not json {{{")
        c = self._client(max_credits=100)
        c._reserve_budget_slot(10)  # Must not raise.
        data = json.loads(self.budget_path.read_text())
        self.assertEqual(data["credits_used"], 10)

    def test_old_month_file_starts_fresh(self) -> None:
        self.budget_path.parent.mkdir(parents=True, exist_ok=True)
        self.budget_path.write_text(json.dumps({"month": "1999-01", "credits_used": 99999}))
        c = self._client(max_credits=100)
        c._reserve_budget_slot(10)
        data = json.loads(self.budget_path.read_text())
        # New-month rollover — old huge counter must be ignored.
        self.assertEqual(data["credits_used"], 10)

    def test_fetch_html_returns_none_when_budget_exhausted(self) -> None:
        c = self._client(max_credits=5)  # Smaller than premium cost (10).
        result = c.fetch_html("https://example.com", premium=True, render=False)
        # Premium=10 credits, cap=5, so first call must be refused before HTTP.
        self.assertIsNone(result)
        # Counter file was never written (no slot reserved).
        self.assertFalse(self.budget_path.exists())


if __name__ == "__main__":
    unittest.main()

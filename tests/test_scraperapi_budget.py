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
from unittest.mock import MagicMock, patch

import requests

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


class ScraperAPIHTTPPathTests(unittest.TestCase):
    """Cover the three bugs fixed in the ScraperAPI hardening pass:

    1. api_key must travel as a header, never in URL params (key-leak fix).
    2. 401 responses must propagate up so misconfig crashes loudly.
    3. Timeout / ConnectionError must be retried inside _get_with_retries
       rather than bubbling out and short-circuiting the retry loop.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.budget_path = pathlib.Path(self._tmp.name) / "budget.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _client(self, max_retries: int = 2) -> ScraperAPIClient:
        return ScraperAPIClient(
            api_key="secret-key-do-not-leak",
            rate_limit_qps=0,
            jitter_ms=0,
            max_retries=max_retries,
            backoff_base_s=0,  # Skip real sleeps in tests.
            backoff_max_s=0,
            max_monthly_credits=10_000,
            budget_state_path=self.budget_path,
        )

    def test_api_key_sent_as_header_not_query_param(self) -> None:
        c = self._client()
        mock_resp = MagicMock(spec=requests.Response)
        mock_resp.status_code = 200
        mock_resp.text = "<html>ok</html>"

        with patch.object(c._session, "get", return_value=mock_resp) as mock_get:
            result = c.fetch_html("https://yelp.com/biz/foo", premium=True)

        self.assertEqual(result, "<html>ok</html>")
        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args

        # Key must be in headers...
        self.assertEqual(
            kwargs["headers"], {"x-sapi-api_key": "secret-key-do-not-leak"}
        )
        # ...and absent from params (so it never lands in resp.url or in any
        # HTTPError message that requests builds from the prepared URL).
        self.assertNotIn("api_key", kwargs["params"])
        self.assertNotIn(
            "secret-key-do-not-leak", json.dumps(kwargs["params"])
        )

    def test_401_propagates_through_fetch_html(self) -> None:
        """A bad SCRAPERAPI_KEY must crash, not silently return None."""
        c = self._client()
        mock_resp = MagicMock(spec=requests.Response)
        mock_resp.status_code = 401
        # raise_for_status must raise an HTTPError carrying the response.
        http_err = requests.HTTPError("401 Unauthorized", response=mock_resp)
        mock_resp.raise_for_status.side_effect = http_err

        with patch.object(c._session, "get", return_value=mock_resp):
            with self.assertRaises(requests.HTTPError) as ctx:
                c.fetch_html("https://yelp.com/biz/foo", premium=True)

        self.assertEqual(ctx.exception.response.status_code, 401)

    def test_timeout_retries_then_returns_none(self) -> None:
        """Timeout must be caught inside the retry loop and back off, not
        propagate up where fetch_html's narrow except would still swallow
        it but skip the retries entirely (the original bug)."""
        c = self._client(max_retries=2)
        with patch.object(
            c._session, "get", side_effect=requests.Timeout("read timeout")
        ) as mock_get:
            result = c.fetch_html("https://yelp.com/biz/foo", premium=True)

        self.assertIsNone(result)
        # max_retries=2 means 3 total attempts (initial + 2 retries).
        self.assertEqual(mock_get.call_count, 3)

    def test_connection_error_retries_then_returns_none(self) -> None:
        c = self._client(max_retries=1)
        with patch.object(
            c._session,
            "get",
            side_effect=requests.ConnectionError("dns fail"),
        ) as mock_get:
            result = c.fetch_html("https://yelp.com/biz/foo", premium=True)

        self.assertIsNone(result)
        self.assertEqual(mock_get.call_count, 2)

    def test_timeout_then_success_returns_html(self) -> None:
        """A transient Timeout on attempt 0 must not poison subsequent attempts."""
        c = self._client(max_retries=2)
        good_resp = MagicMock(spec=requests.Response)
        good_resp.status_code = 200
        good_resp.text = "<html>recovered</html>"

        with patch.object(
            c._session,
            "get",
            side_effect=[requests.Timeout("flaky"), good_resp],
        ) as mock_get:
            result = c.fetch_html("https://yelp.com/biz/foo", premium=True)

        self.assertEqual(result, "<html>recovered</html>")
        self.assertEqual(mock_get.call_count, 2)


if __name__ == "__main__":
    unittest.main()

"""Tests for tools.BraveSearchClient.

All HTTP traffic is mocked via an injected requests.Session double; no live
calls are made. Rate-limiter timing is exercised by patching tools.time.sleep
and tools.time.monotonic. Mirrors the structure of test_yelp_fusion_client.py
plus an extra group for the per-month budget guard (Brave-specific
defense-in-depth mitigation; see docs/plan-tightening-v1.md).
"""
from __future__ import annotations

import json
import pathlib
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import requests

import tools


def _resp(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    """Build a fake requests.Response with status + .json() payload."""
    r = MagicMock(spec=requests.Response)
    r.status_code = status_code
    r.json.return_value = json_data or {}
    if status_code >= 400:
        err = requests.HTTPError(f"{status_code} error", response=r)
        r.raise_for_status.side_effect = err
    else:
        r.raise_for_status.return_value = None
    return r


class BraveSearchClientConstructorTest(unittest.TestCase):
    def test_constructor_requires_api_key(self):
        with self.assertRaises(RuntimeError) as ctx:
            tools.BraveSearchClient(api_key="")
        self.assertIn("BRAVE_SEARCH_KEY", str(ctx.exception))


class BraveSearchClientSearchTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = pathlib.Path(tempfile.mkdtemp())
        self.budget_path = self.tmpdir / "budget.json"
        self.session = MagicMock(spec=requests.Session)
        self.sleep_patch = patch("tools.time.sleep", return_value=None)
        self.monotonic_patch = patch("tools.time.monotonic", return_value=0.0)
        self.sleep_patch.start()
        self.monotonic_patch.start()
        self.client = tools.BraveSearchClient(
            api_key="fake-brave-key",
            session=self.session,
            jitter_ms=0,
            budget_state_path=self.budget_path,
            max_monthly_queries=1000,
        )

    def tearDown(self):
        self.sleep_patch.stop()
        self.monotonic_patch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_search_web_uses_subscription_token_header(self):
        self.session.get.return_value = _resp(200, {"web": {"results": []}})
        self.client.search_web(query="abc remodeling Orlando FL")
        _, kwargs = self.session.get.call_args
        headers = kwargs["headers"]
        self.assertEqual(headers["X-Subscription-Token"], "fake-brave-key")
        self.assertEqual(headers["Accept"], "application/json")
        # Critical: must not appear as a query param.
        self.assertNotIn("X-Subscription-Token", kwargs["params"])

    def test_search_web_clamps_count_to_max(self):
        self.session.get.return_value = _resp(200, {"web": {"results": []}})
        self.client.search_web(query="anything", count=50)
        _, kwargs = self.session.get.call_args
        self.assertEqual(kwargs["params"]["count"], 20)

    def test_search_web_returns_results_list(self):
        payload = {
            "web": {
                "results": [
                    {"title": "ACME", "url": "https://acme.com"},
                    {"title": "Foo", "url": "https://foo.com"},
                ]
            }
        }
        self.session.get.return_value = _resp(200, payload)
        out = self.client.search_web(query="anything")
        self.assertEqual(out, payload["web"]["results"])

    def test_search_web_returns_empty_when_no_results(self):
        self.session.get.return_value = _resp(200, {})
        out = self.client.search_web(query="anything")
        self.assertEqual(out, [])


class BraveSearchClientBackoffTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = pathlib.Path(tempfile.mkdtemp())
        self.budget_path = self.tmpdir / "budget.json"
        self.session = MagicMock(spec=requests.Session)
        self.sleep_patch = patch("tools.time.sleep", return_value=None)
        self.monotonic_patch = patch("tools.time.monotonic", return_value=0.0)
        self.mock_sleep = self.sleep_patch.start()
        self.monotonic_patch.start()
        self.client = tools.BraveSearchClient(
            api_key="fake-brave-key",
            session=self.session,
            jitter_ms=0,
            backoff_base_s=1.0,
            backoff_max_s=4.0,
            max_retries=3,
            budget_state_path=self.budget_path,
            max_monthly_queries=1000,
        )

    def tearDown(self):
        self.sleep_patch.stop()
        self.monotonic_patch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_429_triggers_backoff_then_succeeds(self):
        self.session.get.side_effect = [
            _resp(429),
            _resp(200, {"web": {"results": [{"url": "https://x.com"}]}}),
        ]
        out = self.client.search_web(query="anything")
        self.assertEqual(self.session.get.call_count, 2)
        self.assertEqual(out, [{"url": "https://x.com"}])

    def test_500_triggers_backoff_then_succeeds(self):
        self.session.get.side_effect = [
            _resp(503),
            _resp(200, {"web": {"results": [{"url": "https://y.com"}]}}),
        ]
        out = self.client.search_web(query="anything")
        self.assertEqual(self.session.get.call_count, 2)
        self.assertEqual(out, [{"url": "https://y.com"}])

    def test_max_retries_exceeded_raises_http_error(self):
        self.session.get.side_effect = [
            _resp(429),
            _resp(429),
            _resp(429),
            _resp(429),
        ]
        with self.assertRaises(requests.HTTPError):
            self.client.search_web(query="anything")

    def test_4xx_other_than_429_raises_immediately(self):
        self.session.get.return_value = _resp(401)
        with self.assertRaises(requests.HTTPError):
            self.client.search_web(query="anything")
        # Critical: only one call. No back-off retry on 401.
        self.assertEqual(self.session.get.call_count, 1)


class BraveSearchClientBudgetGuardTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = pathlib.Path(tempfile.mkdtemp())
        self.session = MagicMock(spec=requests.Session)
        self.sleep_patch = patch("tools.time.sleep", return_value=None)
        self.monotonic_patch = patch("tools.time.monotonic", return_value=0.0)
        self.sleep_patch.start()
        self.monotonic_patch.start()

    def tearDown(self):
        self.sleep_patch.stop()
        self.monotonic_patch.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_client(self, *, max_q: int, path: pathlib.Path) -> "tools.BraveSearchClient":
        return tools.BraveSearchClient(
            api_key="fake-brave-key",
            session=self.session,
            jitter_ms=0,
            budget_state_path=path,
            max_monthly_queries=max_q,
        )

    def test_budget_guard_initializes_counter_file(self):
        budget_path = self.tmpdir / "budget_a.json"
        client = self._make_client(max_q=10, path=budget_path)
        self.session.get.return_value = _resp(200, {"web": {"results": []}})
        client.search_web(query="anything")
        self.assertTrue(budget_path.exists())
        data = json.loads(budget_path.read_text())
        self.assertEqual(data["count"], 1)
        self.assertIn("month", data)

    def test_budget_guard_increments_per_call(self):
        budget_path = self.tmpdir / "budget_b.json"
        client = self._make_client(max_q=10, path=budget_path)
        self.session.get.return_value = _resp(200, {"web": {"results": []}})
        for _ in range(3):
            client.search_web(query="anything")
        data = json.loads(budget_path.read_text())
        self.assertEqual(data["count"], 3)

    def test_budget_guard_raises_when_max_reached(self):
        budget_path = self.tmpdir / "budget_c.json"
        client = self._make_client(max_q=2, path=budget_path)
        self.session.get.return_value = _resp(200, {"web": {"results": []}})
        client.search_web(query="anything")
        client.search_web(query="anything")
        # 3rd call must NOT fire HTTP and must raise.
        self.session.get.reset_mock()
        with self.assertRaises(tools.BraveBudgetExceededError):
            client.search_web(query="anything")
        self.assertEqual(self.session.get.call_count, 0)

    def test_budget_guard_resets_for_new_month(self):
        budget_path_old = self.tmpdir / "budget_2026-04.json"
        budget_path_old.write_text(json.dumps({"month": "2026-04", "count": 99}))
        # Use a different month's file path — fresh start expected.
        budget_path_new = self.tmpdir / "budget_2026-05.json"
        client = self._make_client(max_q=10, path=budget_path_new)
        self.session.get.return_value = _resp(200, {"web": {"results": []}})
        client.search_web(query="anything")
        data = json.loads(budget_path_new.read_text())
        self.assertEqual(data["count"], 1)


if __name__ == "__main__":
    unittest.main()

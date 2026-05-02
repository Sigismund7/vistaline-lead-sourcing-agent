"""Tests for tools.YelpFusionClient.

All HTTP traffic is mocked via an injected requests.Session double; no live
calls are made. Rate-limiter timing is exercised by patching tools.time.sleep
and tools.time.monotonic. Mirrors the structure of test_azure_maps_client.py.
"""
from __future__ import annotations

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


class YelpFusionClientConstructorTest(unittest.TestCase):
    def test_constructor_requires_api_key(self):
        with self.assertRaises(RuntimeError) as ctx:
            tools.YelpFusionClient(api_key="")
        self.assertIn("YELP_FUSION_KEY", str(ctx.exception))


class YelpFusionClientSearchTest(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock(spec=requests.Session)
        self.sleep_patch = patch("tools.time.sleep", return_value=None)
        self.monotonic_patch = patch("tools.time.monotonic", return_value=0.0)
        self.sleep_patch.start()
        self.monotonic_patch.start()
        self.client = tools.YelpFusionClient(
            api_key="fake-yelp-key", session=self.session, jitter_ms=0
        )

    def tearDown(self):
        self.sleep_patch.stop()
        self.monotonic_patch.stop()

    def test_search_businesses_uses_bearer_auth_header(self):
        self.session.get.return_value = _resp(200, {"businesses": []})
        self.client.search_businesses(location="Orlando, FL")
        _, kwargs = self.session.get.call_args
        headers = kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer fake-yelp-key")

    def test_search_businesses_includes_categories_param(self):
        self.session.get.return_value = _resp(200, {"businesses": []})
        self.client.search_businesses(
            location="Orlando, FL",
            categories="contractors,kitchen_and_bath,homeservices",
        )
        _, kwargs = self.session.get.call_args
        self.assertEqual(
            kwargs["params"]["categories"],
            "contractors,kitchen_and_bath,homeservices",
        )

    def test_search_businesses_clamps_limit_to_50(self):
        self.session.get.return_value = _resp(200, {"businesses": []})
        self.client.search_businesses(location="Orlando, FL", limit=100)
        _, kwargs = self.session.get.call_args
        self.assertEqual(kwargs["params"]["limit"], 50)

    def test_search_businesses_clamps_radius_to_40000(self):
        self.session.get.return_value = _resp(200, {"businesses": []})
        self.client.search_businesses(location="Orlando, FL", radius_m=50000)
        _, kwargs = self.session.get.call_args
        self.assertEqual(kwargs["params"]["radius"], 40000)

    def test_search_businesses_passes_offset_for_pagination(self):
        self.session.get.return_value = _resp(200, {"businesses": []})
        self.client.search_businesses(location="Orlando, FL", offset=50)
        _, kwargs = self.session.get.call_args
        self.assertEqual(kwargs["params"]["offset"], 50)

    def test_search_businesses_returns_businesses_list(self):
        payload = {
            "businesses": [
                {"id": "b1", "name": "Foo"},
                {"id": "b2", "name": "Bar"},
            ]
        }
        self.session.get.return_value = _resp(200, payload)
        out = self.client.search_businesses(location="Orlando, FL")
        self.assertEqual(out, payload["businesses"])

    def test_search_businesses_returns_empty_when_no_businesses(self):
        self.session.get.return_value = _resp(200, {})
        out = self.client.search_businesses(location="Orlando, FL")
        self.assertEqual(out, [])


class YelpFusionClientBackoffTest(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock(spec=requests.Session)
        self.sleep_patch = patch("tools.time.sleep", return_value=None)
        self.monotonic_patch = patch("tools.time.monotonic", return_value=0.0)
        self.mock_sleep = self.sleep_patch.start()
        self.monotonic_patch.start()
        self.client = tools.YelpFusionClient(
            api_key="fake-yelp-key",
            session=self.session,
            jitter_ms=0,
            backoff_base_s=1.0,
            backoff_max_s=4.0,
            max_retries=3,
        )

    def tearDown(self):
        self.sleep_patch.stop()
        self.monotonic_patch.stop()

    def test_429_triggers_backoff_then_succeeds(self):
        self.session.get.side_effect = [
            _resp(429),
            _resp(200, {"businesses": [{"id": "abc"}]}),
        ]
        out = self.client.search_businesses(location="Orlando, FL")
        self.assertEqual(self.session.get.call_count, 2)
        self.assertEqual(out, [{"id": "abc"}])

    def test_500_triggers_backoff_then_succeeds(self):
        self.session.get.side_effect = [
            _resp(503),
            _resp(200, {"businesses": [{"id": "y"}]}),
        ]
        out = self.client.search_businesses(location="Orlando, FL")
        self.assertEqual(self.session.get.call_count, 2)
        self.assertEqual(out, [{"id": "y"}])

    def test_max_retries_exceeded_raises_http_error(self):
        self.session.get.side_effect = [
            _resp(429),
            _resp(429),
            _resp(429),
            _resp(429),
        ]
        with self.assertRaises(requests.HTTPError):
            self.client.search_businesses(location="Orlando, FL")

    def test_4xx_other_than_429_raises_immediately(self):
        self.session.get.return_value = _resp(401)
        with self.assertRaises(requests.HTTPError):
            self.client.search_businesses(location="Orlando, FL")
        # Critical: only one call. No back-off retry on 401.
        self.assertEqual(self.session.get.call_count, 1)


class YelpFusionClientRateLimitTest(unittest.TestCase):
    def test_rate_limiter_timestamp_updates_on_exception(self):
        """try/finally: a network exception still bumps _last_call_ts so
        retries respect the configured QPS spacing.
        """
        session = MagicMock(spec=requests.Session)
        session.get.side_effect = requests.ConnectionError("network down")

        time_values = iter([0.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0])
        with patch("tools.time.sleep"), patch(
            "tools.time.monotonic", side_effect=lambda: next(time_values)
        ):
            client = tools.YelpFusionClient(
                api_key="fake-yelp-key",
                session=session,
                rate_limit_qps=1.0,
                jitter_ms=0,
                max_retries=0,
            )
            with self.assertRaises(requests.ConnectionError):
                client.search_businesses(location="Orlando, FL")
            # Even though .get() raised, the last-call timestamp got bumped
            # by the try/finally — so it should NOT be the original -inf.
            self.assertNotEqual(client._last_call_ts, float("-inf"))


if __name__ == "__main__":
    unittest.main()

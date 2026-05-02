"""Tests for tools.AzureMapsClient.

All HTTP traffic is mocked via an injected requests.Session double; no live
calls are made. Rate-limiter timing is exercised by patching tools.time.sleep
and tools.time.monotonic.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import requests

import tools


def _resp(status_code: int = 200, json_data: dict | None = None) -> MagicMock:
    """Build a fake requests.Response with status + .json() payload.

    raise_for_status mirrors requests' behaviour so back-off paths exercise the
    same code-flow they would in production.
    """
    r = MagicMock(spec=requests.Response)
    r.status_code = status_code
    r.json.return_value = json_data or {}
    if status_code >= 400:
        err = requests.HTTPError(f"{status_code} error", response=r)
        r.raise_for_status.side_effect = err
    else:
        r.raise_for_status.return_value = None
    return r


class AzureMapsClientConstructorTest(unittest.TestCase):
    def test_constructor_requires_api_key(self):
        with self.assertRaises(RuntimeError) as ctx:
            tools.AzureMapsClient(api_key="")
        self.assertIn("AZURE_MAPS_KEY", str(ctx.exception))


class AzureMapsClientGeocodeTest(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock(spec=requests.Session)
        # Disable real timing so tests stay fast.
        self.sleep_patch = patch("tools.time.sleep", return_value=None)
        self.monotonic_patch = patch("tools.time.monotonic", return_value=0.0)
        self.sleep_patch.start()
        self.monotonic_patch.start()
        self.client = tools.AzureMapsClient(
            api_key="fake-key", session=self.session, jitter_ms=0
        )

    def tearDown(self):
        self.sleep_patch.stop()
        self.monotonic_patch.stop()

    def test_geocode_returns_lat_lon(self):
        self.session.get.return_value = _resp(
            200,
            {
                "results": [
                    {"position": {"lat": 28.5383, "lon": -81.3792}}
                ]
            },
        )
        result = self.client.geocode("Orlando, FL")
        self.assertEqual(result, (28.5383, -81.3792))

    def test_geocode_returns_none_on_empty_results(self):
        self.session.get.return_value = _resp(200, {"results": []})
        self.assertIsNone(self.client.geocode("Nowhereville, ZZ"))

    def test_geocode_returns_none_when_position_missing(self):
        self.session.get.return_value = _resp(
            200, {"results": [{"address": {}}]}
        )
        self.assertIsNone(self.client.geocode("Orlando, FL"))


class AzureMapsClientPoiSearchTest(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock(spec=requests.Session)
        self.sleep_patch = patch("tools.time.sleep", return_value=None)
        self.monotonic_patch = patch("tools.time.monotonic", return_value=0.0)
        self.sleep_patch.start()
        self.monotonic_patch.start()
        self.client = tools.AzureMapsClient(
            api_key="fake-key", session=self.session, jitter_ms=0
        )

    def tearDown(self):
        self.sleep_patch.stop()
        self.monotonic_patch.stop()

    def test_search_poi_includes_subscription_key(self):
        self.session.get.return_value = _resp(200, {"results": []})
        self.client.search_poi(
            "kitchen remodeling", lat=28.5, lon=-81.3, radius_m=10000, limit=5
        )
        _, kwargs = self.session.get.call_args
        self.assertEqual(kwargs["params"]["subscription-key"], "fake-key")

    def test_search_poi_includes_category_set_when_provided(self):
        self.session.get.return_value = _resp(200, {"results": []})
        self.client.search_poi(
            "kitchen remodeling",
            lat=28.5,
            lon=-81.3,
            category_set="7320",
        )
        args, kwargs = self.session.get.call_args
        url = args[0]
        self.assertIn("/search/poi/category/json", url)
        self.assertEqual(kwargs["params"]["categorySet"], "7320")

    def test_search_poi_uses_text_endpoint_when_no_category(self):
        self.session.get.return_value = _resp(200, {"results": []})
        self.client.search_poi(
            "kitchen remodeling", lat=28.5, lon=-81.3, category_set=None
        )
        args, _ = self.session.get.call_args
        url = args[0]
        self.assertIn("/search/poi/json", url)
        self.assertNotIn("/search/poi/category/json", url)


class AzureMapsClientBackoffTest(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock(spec=requests.Session)
        self.sleep_patch = patch("tools.time.sleep", return_value=None)
        self.monotonic_patch = patch("tools.time.monotonic", return_value=0.0)
        self.mock_sleep = self.sleep_patch.start()
        self.monotonic_patch.start()
        self.client = tools.AzureMapsClient(
            api_key="fake-key",
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
            _resp(200, {"results": [{"id": "abc"}]}),
        ]
        out = self.client.search_poi("x", lat=0.0, lon=0.0)
        self.assertEqual(self.session.get.call_count, 2)
        self.assertEqual(out, [{"id": "abc"}])

    def test_500_triggers_backoff_then_succeeds(self):
        self.session.get.side_effect = [
            _resp(503),
            _resp(200, {"results": [{"id": "y"}]}),
        ]
        out = self.client.search_poi("x", lat=0.0, lon=0.0)
        self.assertEqual(self.session.get.call_count, 2)
        self.assertEqual(out, [{"id": "y"}])

    def test_max_retries_exceeded_raises(self):
        self.session.get.side_effect = [
            _resp(429),
            _resp(429),
            _resp(429),
            _resp(429),
        ]
        with self.assertRaises((requests.HTTPError, RuntimeError)):
            self.client.search_poi("x", lat=0.0, lon=0.0)

    def test_4xx_other_than_429_raises_immediately(self):
        self.session.get.return_value = _resp(401)
        with self.assertRaises(requests.HTTPError):
            self.client.search_poi("x", lat=0.0, lon=0.0)
        # Critical: only one call. No back-off retry on 401.
        self.assertEqual(self.session.get.call_count, 1)


class AzureMapsClientRateLimitTest(unittest.TestCase):
    def test_rate_limiter_calls_sleep_between_consecutive_calls(self):
        """Two back-to-back calls force a sleep when interval not yet elapsed."""
        session = MagicMock(spec=requests.Session)
        session.get.return_value = _resp(200, {"results": []})

        # monotonic() returns deterministic ticks; first call records t=0, the
        # rate-limiter checks the elapsed before the second call (t=0.1) — well
        # within 1/qps=0.667s, so it must sleep.
        time_values = iter([0.0, 0.0, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1])
        with patch("tools.time.sleep") as mock_sleep, patch(
            "tools.time.monotonic", side_effect=lambda: next(time_values)
        ):
            client = tools.AzureMapsClient(
                api_key="fake-key",
                session=session,
                rate_limit_qps=1.5,
                jitter_ms=0,
            )
            client.search_poi("x", lat=0.0, lon=0.0)
            client.search_poi("x", lat=0.0, lon=0.0)
            self.assertTrue(
                mock_sleep.called,
                msg="rate-limiter should sleep when consecutive calls "
                "fall inside the QPS window",
            )


if __name__ == "__main__":
    unittest.main()

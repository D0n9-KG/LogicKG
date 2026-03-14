from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import app.crossref.client as crossref_module
from app.crossref.client import CrossrefClient


class _Resp:
    def __init__(self, status_code: int, retry_after: str | None = None):
        self.status_code = status_code
        self.headers = {}
        if retry_after is not None:
            self.headers["Retry-After"] = retry_after


class _JsonResp(_Resp):
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"message": {"items": []}}


class CrossrefClientRateLimitTests(unittest.TestCase):
    def test_retry_after_seconds_clamped(self) -> None:
        self.assertEqual(CrossrefClient._retry_after_seconds(None), 2.0)
        self.assertEqual(CrossrefClient._retry_after_seconds("0"), 0.2)
        self.assertEqual(CrossrefClient._retry_after_seconds("5"), 5.0)
        self.assertEqual(CrossrefClient._retry_after_seconds("999"), 60.0)

    def test_raise_if_rate_limited_waits_then_raises(self) -> None:
        client = CrossrefClient()
        with patch("app.crossref.client.time.sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "rate limited"):
                client._raise_if_rate_limited(_Resp(status_code=429, retry_after="3"))
        sleep.assert_called_once_with(3.0)

    def test_raise_if_rate_limited_noop_for_non_429(self) -> None:
        client = CrossrefClient()
        with patch("app.crossref.client.time.sleep") as sleep:
            client._raise_if_rate_limited(_Resp(status_code=200))
        sleep.assert_not_called()

    def test_query_uses_configured_mailto_and_user_agent(self) -> None:
        fake_settings = SimpleNamespace(
            crossref_mailto="ops@example.com",
            crossref_user_agent="LogicKG-Test/1.0",
            crossref_max_concurrent=2,
            crossref_min_interval_seconds=0.12,
        )
        with patch.object(crossref_module, "settings", fake_settings, create=True):
            client = CrossrefClient()
            calls: list[dict] = []

            def fake_get(url: str, params: dict | None = None, timeout: int | float | None = None):
                calls.append({"url": url, "params": dict(params or {}), "timeout": timeout})
                return _JsonResp(status_code=200)

            with patch.object(client._session, "get", side_effect=fake_get):
                client._query("granular flow", rows=3)

        self.assertEqual(client._mailto, "ops@example.com")
        self.assertIn("LogicKG-Test/1.0", client._session.headers.get("User-Agent", ""))
        self.assertEqual(calls[0]["params"].get("mailto"), "ops@example.com")


if __name__ == "__main__":
    unittest.main()


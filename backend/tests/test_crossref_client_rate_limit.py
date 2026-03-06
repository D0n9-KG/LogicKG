from __future__ import annotations

import unittest
from unittest.mock import patch

from app.crossref.client import CrossrefClient


class _Resp:
    def __init__(self, status_code: int, retry_after: str | None = None):
        self.status_code = status_code
        self.headers = {}
        if retry_after is not None:
            self.headers["Retry-After"] = retry_after


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


if __name__ == "__main__":
    unittest.main()


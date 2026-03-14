from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from app.settings import settings


@dataclass(frozen=True)
class CrossrefWork:
    doi: str | None
    title: str | None
    year: int | None
    venue: str | None
    authors: list[str]
    score: float | None


@dataclass(frozen=True)
class CrossrefResolveResult:
    query: str
    topk: list[CrossrefWork]
    selected: CrossrefWork | None
    confidence: float


class _CrossrefLimiter:
    def __init__(self, max_concurrent: int, min_interval_seconds: float):
        self._semaphore = threading.BoundedSemaphore(max(1, int(max_concurrent)))
        self._min_interval_seconds = max(0.0, float(min_interval_seconds))
        self._clock_lock = threading.Lock()
        self._last_started = 0.0

    @contextmanager
    def ticket(self):
        self._semaphore.acquire()
        try:
            if self._min_interval_seconds > 0:
                with self._clock_lock:
                    now = time.monotonic()
                    wait_seconds = self._min_interval_seconds - (now - self._last_started)
                    if wait_seconds > 0:
                        time.sleep(wait_seconds)
                        now = time.monotonic()
                    self._last_started = now
            yield
        finally:
            self._semaphore.release()


_LIMITER_LOCK = threading.Lock()
_LIMITER_CACHE: dict[tuple[int, float], _CrossrefLimiter] = {}


class CrossrefClient:
    # DOI pattern: 10.xxxx/...
    _DOI_RE = re.compile(r"(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.IGNORECASE)

    def __init__(self, mailto: str | None = None):
        self._mailto = self._normalize_mailto(mailto or getattr(settings, "crossref_mailto", None))
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": self._build_user_agent(),
            }
        )
        self._limiter = self._shared_limiter(
            max_concurrent=self.recommended_workers(),
            min_interval_seconds=self._effective_min_interval_seconds(),
        )
        self._cache: dict[str, CrossrefResolveResult] = {}
        self._cache_lock = threading.Lock()

    @staticmethod
    def _normalize_mailto(raw: str | None) -> str | None:
        s = str(raw or "").strip()
        return s or None

    def _build_user_agent(self) -> str:
        base = str(getattr(settings, "crossref_user_agent", "LogicKG/1.0") or "").strip() or "LogicKG/1.0"
        if self._mailto and "mailto:" not in base.lower():
            return f"{base} (mailto: {self._mailto})"
        return base

    def _effective_min_interval_seconds(self) -> float:
        try:
            configured = float(getattr(settings, "crossref_min_interval_seconds", 0.12))
        except Exception:  # noqa: BLE001
            configured = 0.12
        baseline = 0.12 if self._mailto else 0.25
        return max(baseline, configured)

    def recommended_workers(self) -> int:
        try:
            configured = int(getattr(settings, "crossref_max_concurrent", 2))
        except Exception:  # noqa: BLE001
            configured = 2
        max_pool_concurrency = 3 if self._mailto else 1
        return max(1, min(configured, max_pool_concurrency))

    @classmethod
    def _shared_limiter(cls, *, max_concurrent: int, min_interval_seconds: float) -> _CrossrefLimiter:
        key = (max(1, int(max_concurrent)), round(max(0.0, float(min_interval_seconds)), 3))
        with _LIMITER_LOCK:
            limiter = _LIMITER_CACHE.get(key)
            if limiter is None:
                limiter = _CrossrefLimiter(max_concurrent=key[0], min_interval_seconds=key[1])
                _LIMITER_CACHE[key] = limiter
            return limiter

    def _request_get(self, url: str, *, params: dict | None = None, timeout: float = 15) -> requests.Response:
        with self._limiter.ticket():
            response = self._session.get(url, params=params, timeout=timeout)
        self._raise_if_rate_limited(response)
        response.raise_for_status()
        return response

    @classmethod
    def _extract_doi(cls, raw: str) -> str | None:
        """Extract DOI from reference text if present."""
        m = cls._DOI_RE.search(str(raw or ""))
        if not m:
            return None
        # Strip trailing punctuation that might be caught
        doi = str(m.group(1)).rstrip(").,;]}").lower()
        return doi

    def preflight(self, max_wait_seconds: float = 15.0) -> dict:
        """
        Best-effort check that Crossref is reachable. Designed to fail fast within a fixed wall-clock budget.

        Raises RuntimeError if we cannot successfully complete at least one request within max_wait_seconds.
        """
        deadline = time.monotonic() + float(max(1.0, max_wait_seconds))
        last_exc: Exception | None = None
        attempts = 0

        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            timeout_s = max(1.0, min(5.0, remaining))
            attempts += 1
            try:
                params = {"query.bibliographic": "test", "rows": 1}
                if self._mailto:
                    params["mailto"] = self._mailto
                self._request_get("https://api.crossref.org/works", params=params, timeout=timeout_s)
                return {
                    "ok": True,
                    "attempts": attempts,
                    "checked_at": datetime.now(tz=timezone.utc).isoformat(),
                }
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                # small backoff within the same budget
                time.sleep(0.5)

        raise RuntimeError(f"Crossref preflight failed within {max_wait_seconds:.1f}s: {last_exc}")

    def _cache_key(self, query: str) -> str:
        return hashlib.sha256(query.strip().encode("utf-8", errors="ignore")).hexdigest()

    @staticmethod
    def _retry_after_seconds(retry_after: str | None) -> float:
        try:
            raw = float(str(retry_after or "").strip())
        except Exception:  # noqa: BLE001
            raw = 2.0
        return max(0.2, min(60.0, raw))

    def _raise_if_rate_limited(self, response: requests.Response) -> None:
        if int(response.status_code) != 429:
            return
        time.sleep(self._retry_after_seconds(response.headers.get("Retry-After")))
        raise RuntimeError("Crossref rate limited (429)")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.6, min=0.6, max=3.0))
    def _query(self, query: str, rows: int = 5) -> dict:
        params = {"query.bibliographic": query, "rows": rows}
        if self._mailto:
            params["mailto"] = self._mailto
        r = self._request_get("https://api.crossref.org/works", params=params, timeout=15)
        return r.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.6, min=0.6, max=3.0))
    def _get_work(self, doi: str) -> dict:
        # DOI may contain slashes; requests will handle encoding.
        r = self._request_get(f"https://api.crossref.org/works/{doi}", timeout=15)
        return r.json()

    def get_work_by_doi(self, doi: str) -> CrossrefWork | None:
        try:
            data = self._get_work(doi)
        except Exception:
            return None
        it = data.get("message") or {}
        if not it:
            return None
        title = (it.get("title") or [None])[0]
        venue = (it.get("container-title") or [None])[0]
        issued = it.get("issued", {}).get("date-parts", [])
        year = None
        if issued and isinstance(issued, list) and issued[0]:
            try:
                year = int(issued[0][0])
            except Exception:
                year = None
        authors = []
        for a in it.get("author", []) or []:
            given = a.get("given") or ""
            family = a.get("family") or ""
            name = (given + " " + family).strip()
            if name:
                authors.append(name)
        return CrossrefWork(
            doi=str(it.get("DOI")).lower() if it.get("DOI") else doi.lower(),
            title=title,
            year=year,
            venue=venue,
            authors=authors[:8],
            score=None,
        )

    def resolve_reference(self, raw: str, topk: int = 5) -> CrossrefResolveResult:
        query = raw.strip()
        if not query:
            return CrossrefResolveResult(query=raw, topk=[], selected=None, confidence=0.0)

        key = self._cache_key(query)
        with self._cache_lock:
            cached = self._cache.get(key)
        if cached:
            return cached

        # DOI-first strategy: if DOI is present in the reference, query directly
        doi_hint = self._extract_doi(query)
        if doi_hint:
            direct_work = self.get_work_by_doi(doi_hint)
            if direct_work:
                # DOI match has confidence 1.0
                result = CrossrefResolveResult(query=raw, topk=[direct_work], selected=direct_work, confidence=1.0)
                with self._cache_lock:
                    self._cache[key] = result
                return result

        data = self._query(query, rows=topk)
        items = data.get("message", {}).get("items", []) or []
        works: list[CrossrefWork] = []
        for it in items:
            doi = it.get("DOI")
            title = (it.get("title") or [None])[0]
            venue = (it.get("container-title") or [None])[0]
            issued = it.get("issued", {}).get("date-parts", [])
            year = None
            if issued and isinstance(issued, list) and issued[0]:
                try:
                    year = int(issued[0][0])
                except Exception:  # noqa: BLE001
                    year = None
            authors = []
            for a in it.get("author", []) or []:
                given = a.get("given") or ""
                family = a.get("family") or ""
                name = (given + " " + family).strip()
                if name:
                    authors.append(name)
            score = it.get("score")
            try:
                score_f = float(score) if score is not None else None
            except Exception:  # noqa: BLE001
                score_f = None
            works.append(
                CrossrefWork(
                    doi=str(doi).lower() if doi else None,
                    title=title,
                    year=year,
                    venue=venue,
                    authors=authors[:8],
                    score=score_f,
                )
            )

        selected = works[0] if works else None
        confidence = 0.0
        if selected and selected.score is not None:
            # Crossref score is not calibrated; normalize into a rough 0..1 for filtering + UI.
            confidence = min(1.0, max(0.0, selected.score / 100.0))

        res = CrossrefResolveResult(query=raw, topk=works, selected=selected, confidence=confidence)
        with self._cache_lock:
            self._cache[key] = res
        return res

    @staticmethod
    def to_jsonable(result: CrossrefResolveResult) -> dict:
        return {
            "query": result.query,
            "confidence": result.confidence,
            "selected": None
            if not result.selected
            else {
                "doi": result.selected.doi,
                "title": result.selected.title,
                "year": result.selected.year,
                "venue": result.selected.venue,
                "authors": result.selected.authors,
                "score": result.selected.score,
            },
            "topk": [
                {
                    "doi": w.doi,
                    "title": w.title,
                    "year": w.year,
                    "venue": w.venue,
                    "authors": w.authors,
                    "score": w.score,
                }
                for w in result.topk
            ],
        }

    @staticmethod
    def dumps(result: CrossrefResolveResult) -> str:
        return json.dumps(CrossrefClient.to_jsonable(result), ensure_ascii=False)

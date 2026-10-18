"""Fixed-window rate limiting with a Redis backend (shared) and an in-memory backend.

Limits are written as ``"<count>/<period>"`` (period: second, minute, hour, day), for
example ``"10/minute"``. Identifiers (IP addresses, user ids, e-mail addresses) are
hashed before they are used in a key, so no personal data is stored in Redis.

Backend failures: ``RedisRateLimiter.hit`` raises ``RateLimiterUnavailableError`` when
Redis cannot be reached. The *caller* (``app/api/dependencies/rate_limit.py``) decides
per scope: credential endpoints (register, login) fail **closed** with 503, because an
unlimited login endpoint during a Redis outage is an open door for password guessing;
every other scope fails **open** (request allowed, warning log + metric), because those
endpoints are already authenticated and a Redis outage must not take the whole API down.
"""

import hashlib
import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import redis

logger = logging.getLogger(__name__)

_PERIODS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
_KEY_PREFIX = "dip:rl"


@dataclass(frozen=True)
class Rate:
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


def parse_rate(value: str) -> Rate:
    """Parse ``"10/minute"`` (also ``"10/minutes"``); raise ``ValueError`` otherwise."""
    count_text, sep, period_text = value.strip().lower().partition("/")
    period = period_text.strip().removesuffix("s")
    if not sep or not count_text.strip().isdigit() or period not in _PERIODS:
        raise ValueError("rate must look like '<count>/<second|minute|hour|day>'")
    count = int(count_text)
    if count < 1:
        raise ValueError("rate count must be at least 1")
    return Rate(limit=count, window_seconds=_PERIODS[period])


def _hash_identifier(identifier: str) -> str:
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:32]


def _window(rate: Rate, now: float) -> tuple[int, int]:
    """Return ``(window_index, seconds_until_window_end)``."""
    index = int(now // rate.window_seconds)
    remaining = max(1, math.ceil((index + 1) * rate.window_seconds - now))
    return index, remaining


class RateLimiterUnavailableError(Exception):
    """The shared counter store could not be reached (message never contains the URL)."""


class RateLimiter(Protocol):
    def hit(self, scope: str, identifier: str, rate: Rate) -> RateLimitDecision: ...


class MemoryRateLimiter:
    """Per-process limiter for tests and single-process development (not for production)."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._counts: dict[str, tuple[int, int]] = {}
        self._lock = threading.Lock()
        self._clock = clock or time.time

    def hit(self, scope: str, identifier: str, rate: Rate) -> RateLimitDecision:
        now = self._clock()
        index, retry_after = _window(rate, now)
        key = f"{scope}:{_hash_identifier(identifier)}"
        with self._lock:
            window, count = self._counts.get(key, (index, 0))
            if window != index:
                count = 0
            count += 1
            self._counts[key] = (index, count)
            if len(self._counts) > 10_000:
                # Drop entries from older windows so memory stays bounded.
                self._counts = {k: v for k, v in self._counts.items() if v[0] == index}
        allowed = count <= rate.limit
        return RateLimitDecision(
            allowed=allowed,
            limit=rate.limit,
            remaining=max(0, rate.limit - count),
            retry_after_seconds=0 if allowed else retry_after,
        )


class RedisRateLimiter:
    """Shared fixed-window counters (``INCR`` + ``EXPIRE`` in one pipeline)."""

    def __init__(self, redis_url: str, *, timeout_seconds: float = 0.5) -> None:
        self._client = redis.Redis.from_url(
            redis_url,
            socket_connect_timeout=timeout_seconds,
            socket_timeout=timeout_seconds,
        )

    def hit(self, scope: str, identifier: str, rate: Rate) -> RateLimitDecision:
        index, retry_after = _window(rate, time.time())
        key = f"{_KEY_PREFIX}:{scope}:{index}:{_hash_identifier(identifier)}"
        try:
            pipe = self._client.pipeline(transaction=True)
            pipe.incr(key)
            pipe.expire(key, rate.window_seconds + 1)
            count = int(pipe.execute()[0])
        except redis.RedisError as exc:
            raise RateLimiterUnavailableError(type(exc).__name__) from exc
        allowed = count <= rate.limit
        return RateLimitDecision(
            allowed=allowed,
            limit=rate.limit,
            remaining=max(0, rate.limit - count),
            retry_after_seconds=0 if allowed else retry_after,
        )

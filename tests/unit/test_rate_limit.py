import os
import uuid

import pytest

from app.core.config import SettingsError, load_settings
from app.core.rate_limit import (
    MemoryRateLimiter,
    Rate,
    RateLimiterUnavailableError,
    RedisRateLimiter,
    parse_rate,
)

TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("10/minute", Rate(10, 60)),
        ("5/second", Rate(5, 1)),
        ("100/hours", Rate(100, 3600)),
        (" 3 / Day ", Rate(3, 86400)),
    ],
)
def test_parse_rate(value: str, expected: Rate) -> None:
    assert parse_rate(value) == expected


@pytest.mark.parametrize("value", ["", "10", "0/minute", "-1/minute", "ten/minute", "5/week"])
def test_parse_rate_rejects_malformed_values(value: str) -> None:
    with pytest.raises(ValueError, match="rate"):
        parse_rate(value)


def test_invalid_rate_setting_fails_at_startup() -> None:
    with pytest.raises(SettingsError, match="RATE_LIMIT_LOGIN"):
        load_settings(_env_file=None, app_env="test", jwt_secret_key="k" * 40, rate_limit_login="x")


def test_memory_limiter_blocks_after_limit_and_resets_next_window() -> None:
    now = [1000.0]
    limiter = MemoryRateLimiter(clock=lambda: now[0])
    rate = Rate(2, 60)
    decisions = [limiter.hit("login", "1.2.3.4", rate) for _ in range(3)]
    assert [d.allowed for d in decisions] == [True, True, False]
    assert decisions[1].remaining == 0
    assert 1 <= decisions[2].retry_after_seconds <= 60
    # Other identifiers and other scopes have their own buckets.
    assert limiter.hit("login", "5.6.7.8", rate).allowed
    assert limiter.hit("register", "1.2.3.4", rate).allowed
    now[0] += 60
    assert limiter.hit("login", "1.2.3.4", rate).allowed


def test_memory_limiter_stays_bounded() -> None:
    limiter = MemoryRateLimiter(clock=lambda: 0.0)
    for index in range(10_050):
        limiter.hit("s", str(index), Rate(1, 60))
    later = MemoryRateLimiter(clock=lambda: 120.0)
    assert later.hit("s", "0", Rate(1, 60)).allowed


def test_redis_limiter_raises_when_redis_is_unreachable() -> None:
    """The limiter reports the outage; the per-scope policy lives in the dependency."""
    limiter = RedisRateLimiter("redis://127.0.0.1:1/0", timeout_seconds=0.2)
    with pytest.raises(RateLimiterUnavailableError) as excinfo:
        limiter.hit("login", "1.2.3.4", Rate(1, 60))
    assert "127.0.0.1" not in str(excinfo.value)


@pytest.mark.skipif(not TEST_REDIS_URL, reason="needs an authenticated Redis: set TEST_REDIS_URL")
def test_redis_limiter_counts_in_real_redis_and_shares_state_between_instances() -> None:
    scope = f"test-{uuid.uuid4().hex}"
    first = RedisRateLimiter(TEST_REDIS_URL)
    second = RedisRateLimiter(TEST_REDIS_URL)  # e.g. another API process
    rate = Rate(3, 60)
    decisions = [first.hit(scope, "client", rate) for _ in range(2)]
    decisions += [second.hit(scope, "client", rate) for _ in range(2)]
    assert [d.allowed for d in decisions] == [True, True, True, False]
    assert decisions[-1].retry_after_seconds >= 1
    assert second.hit(scope, "another-client", rate).allowed

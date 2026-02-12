from __future__ import annotations

from app.core.config import PlatformRateLimit
from app.core.rate_limit import PlatformLimiter, execute_with_retry


def test_execute_with_retry_succeeds_after_failures():
    limiter = PlatformLimiter(
        PlatformRateLimit(
            requests_per_minute=1000,
            jitter_min_seconds=0,
            jitter_max_seconds=0,
            retry_max_attempts=3,
            retry_base_seconds=0.001,
            circuit_breaker_threshold=10,
            circuit_breaker_cooldown_seconds=1,
        )
    )
    state = {"attempt": 0}

    def op():
        state["attempt"] += 1
        if state["attempt"] < 3:
            raise RuntimeError("transient")
        return "ok"

    result = execute_with_retry(op, limiter, attempts=3, base_seconds=0.001)
    assert result == "ok"
    assert state["attempt"] == 3

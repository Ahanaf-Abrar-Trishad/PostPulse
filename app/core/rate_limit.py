from __future__ import annotations

import random
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, TypeVar

from app.core.config import PlatformRateLimit

T = TypeVar("T")


@dataclass
class CircuitBreaker:
    failure_threshold: int
    cooldown_seconds: int
    failures: int = 0
    opened_at: datetime | None = None

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        if datetime.now(timezone.utc) >= self.opened_at + timedelta(seconds=self.cooldown_seconds):
            self.reset()
            return True
        return False

    def record_success(self) -> None:
        self.reset()

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = datetime.now(timezone.utc)

    def reset(self) -> None:
        self.failures = 0
        self.opened_at = None


@dataclass
class TokenBucketLimiter:
    per_minute: int
    timestamps: deque[float] = field(default_factory=deque)

    def acquire(self) -> None:
        now = time.monotonic()
        window_start = now - 60.0
        while self.timestamps and self.timestamps[0] < window_start:
            self.timestamps.popleft()

        if len(self.timestamps) >= self.per_minute:
            sleep_for = 60.0 - (now - self.timestamps[0]) + 0.01
            time.sleep(max(sleep_for, 0.0))
            self.acquire()
            return

        self.timestamps.append(time.monotonic())


class PlatformLimiter:
    def __init__(self, config: PlatformRateLimit) -> None:
        self.config = config
        self.bucket = TokenBucketLimiter(per_minute=config.requests_per_minute)
        self.breaker = CircuitBreaker(
            failure_threshold=config.circuit_breaker_threshold,
            cooldown_seconds=config.circuit_breaker_cooldown_seconds,
        )

    def before_request(self) -> None:
        if not self.breaker.allow():
            raise RuntimeError("Circuit breaker open due to repeated failures")
        self.bucket.acquire()
        jitter = random.uniform(
            self.config.jitter_min_seconds, self.config.jitter_max_seconds
        )
        if jitter > 0:
            time.sleep(jitter)

    def on_success(self) -> None:
        self.breaker.record_success()

    def on_failure(self) -> None:
        self.breaker.record_failure()


def execute_with_retry(
    operation: Callable[[], T],
    limiter: PlatformLimiter,
    attempts: int,
    base_seconds: float,
) -> T:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        limiter.before_request()
        try:
            result = operation()
        except Exception as exc:  # noqa: BLE001 - retries should catch transient errors
            limiter.on_failure()
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(base_seconds * (2 ** (attempt - 1)) + random.uniform(0.0, 0.4))
            continue
        limiter.on_success()
        return result
    if last_error is None:
        raise RuntimeError("Retry failed without captured exception")
    raise last_error

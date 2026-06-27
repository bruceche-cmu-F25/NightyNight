import time
from collections import defaultdict

from fastapi import HTTPException


class RateLimiter:
    """Sliding-window in-memory rate limiter keyed by an arbitrary string.

    One adapter of a seam — swap for Redis-backed adapter when horizontal
    scaling makes per-process limits unsafe.
    """

    def __init__(self, window: int = 60, max_attempts: int = 5) -> None:
        self._window = window
        self._max    = max_attempts
        self._log: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> None:
        """Raise HTTP 429 if `key` has exceeded the allowed rate; otherwise record the attempt."""
        now = time.time()
        self._log[key] = [t for t in self._log[key] if now - t < self._window]
        if len(self._log[key]) >= self._max:
            raise HTTPException(
                status_code=429,
                detail="Too many attempts, please try again later",
            )
        self._log[key].append(now)


# Default singleton used by auth routes.
# _max=5 per-process: in multi-worker deployments the effective limit is 5 × workers.
rate_limiter = RateLimiter(window=60, max_attempts=5)

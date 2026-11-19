"""Small bounded sliding-window limiter for a single backend process."""

from collections import OrderedDict, deque
import logging
from threading import Lock
import time

from fastapi import HTTPException, status


class InMemoryRateLimiter:
    def __init__(self, max_keys: int = 20000) -> None:
        self.max_keys = max_keys
        self._events: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()
        self._lock = Lock()

    def allow(self, category: str, identity: str, limit: int, window: int) -> bool:
        now = time.monotonic()
        key = (category, identity)
        with self._lock:
            events = self._events.get(key)
            if events is None:
                if len(self._events) >= self.max_keys:
                    self._prune(now, window)
                if len(self._events) >= self.max_keys:
                    self._events.popitem(last=False)
                events = deque()
                self._events[key] = events
            else:
                self._events.move_to_end(key)

            cutoff = now - window
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True

    def _prune(self, now: float, window: int) -> None:
        cutoff = now - window
        for key, events in list(self._events.items()):
            while events and events[0] <= cutoff:
                events.popleft()
            if not events:
                self._events.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


rate_limiter = InMemoryRateLimiter()
logger = logging.getLogger("relay.rate_limit")


def check_rate_limit(category: str, identity: str, limit: int, window: int) -> None:
    if not rate_limiter.allow(category, identity, limit, window):
        logger.warning(
            "Rate limit rejected",
            extra={"event": "rate_limit.rejected", "category": category, "status_code": 429},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(window)},
        )

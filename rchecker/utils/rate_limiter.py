import asyncio


class RateLimiter:
    """Simple async rate limiter enforcing a global requests-per-second cap."""

    def __init__(self, rate: float | None) -> None:
        if rate is not None and rate <= 0:
            raise ValueError("Rate must be positive or omitted")
        self._interval = 1.0 / rate if rate else None
        self._lock = asyncio.Lock()
        self._next_time = 0.0

    async def wait(self) -> None:
        if self._interval is None:
            return
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            sleep_for = self._next_time - now
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
                now = loop.time()
            self._next_time = max(now, self._next_time) + self._interval

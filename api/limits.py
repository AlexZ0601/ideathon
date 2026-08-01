"""Rate limiting for the endpoints that spend money.

On localhost none of this mattered. On a public URL every visitor's search and
every drafted email bills the owner's OpenAI key, and there is nothing between
a curious friend and a bad afternoon. Cached requests stay free and unlimited —
only work that would call the API counts against a bucket.

In-memory and per-process, which is the right size for this: it resets on
restart, it needs no Redis, and it is not trying to stop a determined attacker.
It is trying to stop an accident.
"""

import os
import threading
import time

WINDOW = 3600.0
PER_IP_HOURLY = int(os.environ.get("RB_LIMIT_IP", "25"))
GLOBAL_DAILY = int(os.environ.get("RB_LIMIT_DAY", "400"))

_lock = threading.Lock()
_by_ip: dict[str, list[float]] = {}
_day: list[float] = []


class RateLimited(Exception):
    def __init__(self, message, retry_after):
        super().__init__(message)
        self.retry_after = int(retry_after)


def _prune(stamps, window, now):
    cutoff = now - window
    while stamps and stamps[0] < cutoff:
        stamps.pop(0)


def check(ip: str):
    """Raises RateLimited if this request should not reach the API."""
    now = time.time()
    with _lock:
        _prune(_day, 86400.0, now)
        if len(_day) >= GLOBAL_DAILY:
            raise RateLimited(
                "This demo has hit its daily API budget. Cached searches still work — "
                "try one of the example problems.",
                _day[0] + 86400.0 - now,
            )

        stamps = _by_ip.setdefault(ip, [])
        _prune(stamps, WINDOW, now)
        if len(stamps) >= PER_IP_HOURLY:
            raise RateLimited(
                f"You've used {PER_IP_HOURLY} live searches this hour. The example "
                "problems are cached and still free to explore.",
                stamps[0] + WINDOW - now,
            )

        stamps.append(now)
        _day.append(now)


def status():
    now = time.time()
    with _lock:
        _prune(_day, 86400.0, now)
        return {"today": len(_day), "daily_cap": GLOBAL_DAILY, "per_ip_hourly": PER_IP_HOURLY}

from __future__ import annotations

from email.utils import parsedate_to_datetime
from pathlib import Path
from threading import Lock
import random
import shutil
import time
from typing import Iterator

import requests

from .control import Control


class RateLimiter:
    def __init__(self, per_second: float):
        self.interval = 1.0 / per_second
        self.next_at = 0.0
        self.lock = Lock()

    def wait(self, control: Control) -> None:
        while True:
            control.checkpoint()
            with self.lock:
                now = time.monotonic()
                delay = self.next_at - now
                if delay <= 0:
                    self.next_at = max(now, self.next_at) + self.interval
                    return
            time.sleep(min(delay, 0.25))


class BandwidthLimiter:
    """Shared strict token bucket; capacity is one second of configured traffic."""

    def __init__(self, mbps: float):
        self.rate = mbps * 1_000_000 / 8
        self.capacity = self.rate
        self.tokens = 0.0
        self.updated = time.monotonic()
        self.lock = Lock()

    def consume(self, count: int, control: Control) -> None:
        remaining = count
        while remaining:
            control.checkpoint()
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                used = min(remaining, int(self.tokens))
                if used:
                    self.tokens -= used
                    remaining -= used
                    continue
                wait = max(0.01, min(0.25, (remaining - self.tokens) / self.rate))
            time.sleep(wait)


def retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
            return max(0.0, parsed.timestamp() - time.time())
        except (TypeError, ValueError, OverflowError):
            return None


class HttpClient:
    def __init__(self, user_agent: str, control: Control, rate: RateLimiter | None = None):
        self.control = control
        self.rate = rate
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": user_agent, "Accept-Encoding": "gzip", "Accept": "*/*"}
        )

    def get(self, url: str, *, params=None, stream: bool = False, timeout=(15, 120), headers=None):
        for attempt in range(8):
            self.control.checkpoint()
            if self.rate:
                self.rate.wait(self.control)
            started = time.monotonic()
            try:
                response = self.session.get(
                    url, params=params, stream=stream, timeout=timeout, headers=headers
                )
            except (requests.Timeout, requests.ConnectionError):
                response = None
            if response is not None and response.status_code < 400:
                # Robot policy asks a 5-second delay after expensive (>1 s) API calls.
                if self.rate and time.monotonic() - started > 1:
                    self.rate.next_at = max(self.rate.next_at, time.monotonic() + 5)
                return response
            if response is not None and response.status_code not in (429, 500, 502, 503, 504):
                response.raise_for_status()
            if response is not None and response.status_code == 429:
                delay = retry_after_seconds(response.headers.get("Retry-After"))
            else:
                delay = None
            if response is not None:
                response.close()
            delay = delay if delay is not None else min(60.0, 2**attempt + random.random())
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline:
                self.control.checkpoint()
                time.sleep(min(0.25, deadline - time.monotonic()))
        raise RuntimeError(f"request failed after retries: {url}")


def check_free_space(path: Path, minimum_free_gib: float) -> int:
    free = shutil.disk_usage(path).free
    if free < minimum_free_gib * 1024**3:
        raise RuntimeError(
            f"insufficient disk space: {free / 1024**3:.2f} GiB free; "
            f"{minimum_free_gib:.2f} GiB required"
        )
    return free

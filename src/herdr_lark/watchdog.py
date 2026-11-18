from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable

log = logging.getLogger(__name__)

WS_DISCONNECT_LIMIT_SECONDS = 300.0
WS_CHECK_INTERVAL_SECONDS = 5.0


class DisconnectWatchdog:
    """Starts out disconnected, so a connection that never comes up also trips it."""

    def __init__(
        self,
        connected: Callable[[], bool],
        limit: float = WS_DISCONNECT_LIMIT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._connected = connected
        self._limit = limit
        self._clock = clock
        self._down_since: float | None = clock()

    def expired(self) -> bool:
        now = self._clock()
        if self._connected():
            self._down_since = None
            return False
        if self._down_since is None:
            self._down_since = now
        return now - self._down_since > self._limit


def start_watchdog(
    wd: DisconnectWatchdog,
    interval: float = WS_CHECK_INTERVAL_SECONDS,
    on_expired: Callable[[], None] | None = None,
) -> threading.Thread:
    def die() -> None:
        log.critical("lark websocket disconnected too long, exiting for launchd to restart")
        os._exit(1)

    fire = on_expired or die

    def loop() -> None:
        while not wd.expired():
            time.sleep(interval)
        fire()

    t = threading.Thread(target=loop, name="ws-watchdog", daemon=True)
    t.start()
    return t

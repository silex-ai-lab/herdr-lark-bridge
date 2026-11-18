import lark_oapi as lark  # pyright: ignore[reportMissingTypeStubs]

from herdr_lark.lark import ws_connected
from herdr_lark.watchdog import DisconnectWatchdog


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def test_stays_quiet_while_connected_and_during_short_outage():
    clock, up = Clock(), [True]
    wd = DisconnectWatchdog(lambda: up[0], limit=120, clock=clock)
    clock.t = 1000
    assert not wd.expired()
    up[0] = False
    clock.t = 1100
    assert not wd.expired()
    clock.t = 1220
    assert not wd.expired()
    clock.t = 1221
    assert wd.expired()


def test_reconnect_resets_the_outage_clock():
    clock, up = Clock(), [False]
    wd = DisconnectWatchdog(lambda: up[0], limit=120, clock=clock)
    clock.t = 100
    assert not wd.expired()
    up[0] = True
    clock.t = 110
    assert not wd.expired()
    up[0] = False
    clock.t = 200
    assert not wd.expired()
    clock.t = 331
    assert wd.expired()


def test_a_connection_that_never_comes_up_trips_it():
    clock = Clock()
    wd = DisconnectWatchdog(lambda: False, limit=120, clock=clock)
    clock.t = 121
    assert wd.expired()


def test_probe_reads_the_sdk_client_connection_attribute():
    ws = lark.ws.Client("cli_x", "secret")
    assert not ws_connected(ws)
    ws._conn = object()  # type: ignore[assignment]
    assert ws_connected(ws)

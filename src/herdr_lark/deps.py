from __future__ import annotations

import getpass
import sys
from dataclasses import dataclass
from typing import Callable

from .config import Credentials
from .herdr import HerdrCli, HerdrError, HerdrPort, find_binary
from .lark import LarkApi, LarkClient
from .service import Launchctl, subprocess_launchctl


def _find_herdr() -> str | None:
    try:
        return find_binary()
    except HerdrError:
        return None


@dataclass(frozen=True)
class Deps:
    make_lark: Callable[[Credentials], LarkApi]
    make_herdr: Callable[[], HerdrPort]
    find_herdr: Callable[[], str | None]
    launchctl: Launchctl
    platform: str
    ask: Callable[[str], str]
    ask_secret: Callable[[str], str]


def default_deps() -> Deps:
    return Deps(
        make_lark=lambda c: LarkClient(c.app_id, c.app_secret, c.domain),
        make_herdr=HerdrCli,
        find_herdr=_find_herdr,
        launchctl=subprocess_launchctl,
        platform=sys.platform,
        ask=input,
        ask_secret=getpass.getpass,
    )

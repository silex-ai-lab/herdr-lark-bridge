from __future__ import annotations

import argparse
import logging
import sys
import time

from .config import (
    ConfigError,
    load_config,
    load_credentials,
    owner_path,
    pairing_path,
    state_path,
)
from .daemon import Engine, run_daemon
from .herdr import HerdrCli, HerdrError
from .lark import LarkClient, LarkError
from .models import Outbound
from .pairing import PAIRING_TTL_SECONDS, OwnerStore, PairingStore
from .store import StateStore


def _run(_: argparse.Namespace) -> int:
    cfg = load_config()
    creds = load_credentials()
    lark = LarkClient(creds.app_id, creds.app_secret)
    engine = Engine(
        HerdrCli(), lark, StateStore(state_path()), cfg,
        OwnerStore(owner_path()), PairingStore(pairing_path()),
    )
    logging.getLogger(__name__).info("starting, state at %s", state_path())
    run_daemon(engine, lark, cfg.poll_seconds)
    return 0


def _pair(_: argparse.Namespace) -> int:
    owner = OwnerStore(owner_path()).read()
    if owner:
        print(f"already paired with {owner}; run `herdr-lark unpair` first", file=sys.stderr)
        return 1
    p = PairingStore(pairing_path()).arm(time.time())
    print(p.code)
    print(
        f"DM the bot this code within {int(PAIRING_TTL_SECONDS // 60)} minutes. "
        "It is single use and is disarmed after 5 wrong tries.",
        file=sys.stderr,
    )
    return 0


def _unpair(_: argparse.Namespace) -> int:
    OwnerStore(owner_path()).delete()
    PairingStore(pairing_path()).clear()
    print("unpaired: owner file removed")
    return 0


def _status(_: argparse.Namespace) -> int:
    s = StateStore(state_path()).load()
    print(f"state file: {state_path()}")
    print(f"owner: {OwnerStore(owner_path()).read() or 'not paired'}")
    print(f"pending attentions: {len(s.pending)}, notified terminals: {len(s.notified)}, messages tracked: {len(s.messages)}")
    try:
        agents = HerdrCli().list_agents()
    except HerdrError as e:
        print(f"herdr: unavailable ({e})")
        return 1
    print(f"herdr: {len(agents)} agents")
    for a in agents:
        print(f"  {a.workspace_label} / {a.display_name} [{a.agent}] {a.status}")
    return 0


def _send_test(_: argparse.Namespace) -> int:
    owner = OwnerStore(owner_path()).read()
    if not owner:
        print("not paired yet; run `herdr-lark pair` and DM the bot the code", file=sys.stderr)
        return 1
    creds = load_credentials()
    try:
        mid = LarkClient(creds.app_id, creds.app_secret).send_to_user(
            owner,
            Outbound("herdr-lark 测试", "测试消息，桥接已连通。", "echo hello", "可以直接回复本消息试试。"),
        )
    except LarkError as e:
        print(f"send failed: {e}", file=sys.stderr)
        return 1
    print(f"sent {mid}")
    return 0


COMMANDS = {
    "run": _run,
    "pair": _pair,
    "unpair": _unpair,
    "status": _status,
    "send-test": _send_test,
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="herdr-lark")
    p.add_argument("command", choices=sorted(COMMANDS))
    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    try:
        return COMMANDS[args.command](args)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

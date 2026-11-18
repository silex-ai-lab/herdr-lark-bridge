from __future__ import annotations

import argparse
import logging
import sys

from .config import ConfigError, load_config, load_credentials, state_path
from .daemon import Engine, run_daemon
from .herdr import HerdrCli, HerdrError
from .lark import LarkClient, LarkError
from .models import Outbound
from .store import StateStore


def _run(_: argparse.Namespace) -> int:
    cfg = load_config()
    creds = load_credentials()
    lark = LarkClient(creds.app_id, creds.app_secret)
    engine = Engine(HerdrCli(), lark, StateStore(state_path()), cfg)
    logging.getLogger(__name__).info("starting, state at %s", state_path())
    run_daemon(engine, lark, cfg.poll_seconds)
    return 0


def _pair_code(_: argparse.Namespace) -> int:
    s = StateStore(state_path()).load()
    if s.owner_open_id:
        print(f"already paired with {s.owner_open_id}")
        return 0
    if not s.pairing_code:
        print("no pairing code yet; start the daemon first (herdr-lark run)", file=sys.stderr)
        return 1
    print(s.pairing_code)
    return 0


def _status(_: argparse.Namespace) -> int:
    s = StateStore(state_path()).load()
    print(f"state file: {state_path()}")
    print(f"owner: {s.owner_open_id or 'not paired'}")
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
    s = StateStore(state_path()).load()
    if not s.owner_open_id:
        print("not paired yet; DM the bot the pairing code first", file=sys.stderr)
        return 1
    creds = load_credentials()
    try:
        mid = LarkClient(creds.app_id, creds.app_secret).send_to_user(
            s.owner_open_id,
            Outbound("herdr-lark 测试", "测试消息，桥接已连通。", "echo hello", "可以直接回复本消息试试。"),
        )
    except LarkError as e:
        print(f"send failed: {e}", file=sys.stderr)
        return 1
    print(f"sent {mid}")
    return 0


COMMANDS = {"run": _run, "pair-code": _pair_code, "status": _status, "send-test": _send_test}


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

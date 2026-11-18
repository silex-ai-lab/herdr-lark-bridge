from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Callable

from .config import (
    ConfigError,
    load_config,
    load_credentials,
    owner_path,
    pairing_path,
    state_path,
)
from .daemon import Engine, run_daemon
from .deps import Deps, default_deps
from .doctor import run_doctor
from .herdr import HerdrCli, HerdrError
from .lark import LarkClient, LarkError
from .messages import messages
from .models import DOMAINS, Outbound
from .pairing import PAIRING_TTL_SECONDS, OwnerStore, PairingStore
from .service_cli import service_install, service_status, service_uninstall
from .setup import SetupArgs, run_setup
from .store import StateStore


def _run(_: argparse.Namespace, __: Deps) -> int:
    cfg = load_config()
    creds = load_credentials()
    lark = LarkClient(creds.app_id, creds.app_secret, creds.domain)
    engine = Engine(
        HerdrCli(), lark, StateStore(state_path()), cfg,
        OwnerStore(owner_path()), PairingStore(pairing_path()),
    )
    logging.getLogger(__name__).info("starting, state at %s", state_path())
    run_daemon(engine, lark, cfg.poll_seconds)
    return 0


def _pair(_: argparse.Namespace, __: Deps) -> int:
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


def _unpair(_: argparse.Namespace, __: Deps) -> int:
    OwnerStore(owner_path()).delete()
    PairingStore(pairing_path()).clear()
    print("unpaired: owner file removed")
    return 0


def _status(_: argparse.Namespace, __: Deps) -> int:
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


def _send_test(_: argparse.Namespace, __: Deps) -> int:
    owner = OwnerStore(owner_path()).read()
    if not owner:
        print("not paired yet; run `herdr-lark pair` and DM the bot the code", file=sys.stderr)
        return 1
    creds = load_credentials()
    try:
        m = messages(load_config().lang)
        mid = LarkClient(creds.app_id, creds.app_secret, creds.domain).send_to_user(
            owner, Outbound(m.test_title, m.test_text, m.test_code, m.test_footer)
        )
    except LarkError as e:
        print(f"send failed: {e}", file=sys.stderr)
        return 1
    print(f"sent {mid}")
    return 0


def _setup(a: argparse.Namespace, deps: Deps) -> int:
    secret = os.environ.get("LARK_APP_SECRET")
    if a.app_secret_stdin:
        secret = sys.stdin.readline().strip()
    return run_setup(
        SetupArgs(
            domain=a.domain or os.environ.get("LARK_DOMAIN"),
            app_id=a.app_id or os.environ.get("LARK_APP_ID"),
            app_secret=secret,
            non_interactive=a.non_interactive,
            service=a.service,
        ),
        deps,
    )


def _doctor(_: argparse.Namespace, deps: Deps) -> int:
    return run_doctor(deps, Path.home())


def _service(a: argparse.Namespace, deps: Deps) -> int:
    match a.action:
        case "install":
            return service_install(deps, a.dry_run)
        case "uninstall":
            return service_uninstall(deps)
        case _:
            return service_status(deps)


Handler = Callable[[argparse.Namespace, Deps], int]

COMMANDS: dict[str, Handler] = {
    "run": _run,
    "pair": _pair,
    "unpair": _unpair,
    "status": _status,
    "send-test": _send_test,
    "setup": _setup,
    "doctor": _doctor,
    "service": _service,
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="herdr-lark")
    sub = p.add_subparsers(dest="command", required=True)
    helps = {
        "run": "run the bridge in the foreground",
        "pair": "arm pairing and print a code to DM to the bot",
        "unpair": "forget the owner",
        "status": "show owner, tracked state and live agents",
        "send-test": "send a test message to the owner",
        "setup": "enter credentials, verify them, install the service and arm pairing",
        "doctor": "check the whole installation",
        "service": "manage the background service (macOS launchd)",
    }
    for name in COMMANDS:
        sp = sub.add_parser(name, help=helps[name])
        if name == "setup":
            sp.add_argument("--domain", choices=DOMAINS, help="lark (international) or feishu (China)")
            sp.add_argument("--app-id")
            sp.add_argument("--app-secret-stdin", action="store_true", help="read the App Secret from one line of stdin")
            sp.add_argument("--non-interactive", action="store_true", help="never prompt; read values from flags and LARK_* env vars")
            sp.add_argument("--service", action=argparse.BooleanOptionalAction, default=None, help="install the background service without asking")
        if name == "service":
            sp.add_argument("action", choices=("install", "uninstall", "status"))
            sp.add_argument("--dry-run", action="store_true", help="with install: print the plist and change nothing")
    return p


def main(argv: list[str] | None = None, deps: Deps | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    try:
        return COMMANDS[args.command](args, deps or default_deps())
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print("aborted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())

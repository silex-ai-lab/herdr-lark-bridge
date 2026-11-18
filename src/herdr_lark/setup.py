from __future__ import annotations

import sys
import time
from dataclasses import dataclass

from .config import (
    ConfigError,
    Credentials,
    load_credentials,
    owner_path,
    pairing_path,
    parse_domain,
    write_credentials,
)
from .deps import Deps
from .lark import LarkError, api_base
from .models import Domain
from .pairing import PAIRING_TTL_SECONDS, OwnerStore, PairingStore
from .service import supported
from .service_cli import service_install


class SetupError(Exception):
    pass


@dataclass(frozen=True)
class SetupArgs:
    domain: str | None
    app_id: str | None
    app_secret: str | None
    non_interactive: bool
    service: bool | None


def _existing() -> Credentials | None:
    try:
        return load_credentials()
    except ConfigError:
        return None


def _ask_domain(deps: Deps, default: Domain) -> Domain:
    while True:
        raw = deps.ask(
            f"Domain, lark (international, open.larksuite.com) or feishu (China, open.feishu.cn) [{default}]: "
        ).strip().lower()
        try:
            return parse_domain(raw or default)
        except ConfigError as e:
            print(e)


def _gather(args: SetupArgs, deps: Deps, current: Credentials | None) -> Credentials:
    default_domain: Domain = current.domain if current else "lark"
    if args.non_interactive:
        domain = parse_domain(args.domain) if args.domain else default_domain
        app_id = args.app_id or (current.app_id if current else None)
        secret = args.app_secret or (current.app_secret if current else None)
        missing = [
            name
            for name, v in (("--app-id / LARK_APP_ID", app_id), ("LARK_APP_SECRET or --app-secret-stdin", secret))
            if not v
        ]
        if missing or not app_id or not secret:
            raise SetupError(f"non-interactive setup needs {', '.join(missing)}")
        return Credentials(app_id, secret, domain)

    domain = parse_domain(args.domain) if args.domain else _ask_domain(deps, default_domain)
    app_id = args.app_id
    while not app_id:
        hint = f" [{current.app_id}]" if current else ""
        app_id = deps.ask(f"App ID{hint}: ").strip() or (current.app_id if current else "")
    secret = args.app_secret
    while not secret:
        hint = " (Enter keeps the saved one)" if current else ""
        secret = deps.ask_secret(f"App Secret, input hidden{hint}: ").strip() or (
            current.app_secret if current else ""
        )
    return Credentials(app_id, secret, domain)


def _want_service(args: SetupArgs, deps: Deps) -> bool:
    if args.service is not None:
        return args.service
    if args.non_interactive:
        return False
    return deps.ask("Install the background service so the bridge starts at login? [Y/n]: ").strip().lower() in (
        "",
        "y",
        "yes",
    )


def run_setup(args: SetupArgs, deps: Deps) -> int:
    try:
        creds = _gather(args, deps, _existing())
    except (SetupError, ConfigError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    path = write_credentials(creds)
    print(f"[ok] credentials saved to {path} (mode 0600)")

    try:
        deps.make_lark(creds).check_credentials()
    except LarkError as e:
        print(f"[FAIL] could not fetch a tenant access token from {api_base(creds.domain)}: {e}")
        print(
            "       Check the App ID and App Secret, that the domain matches where the app was "
            "created, and that the app is published. Then rerun `herdr-lark setup`."
        )
        return 1
    print(f"[ok] credentials verified against {api_base(creds.domain)}")

    service_running = False
    if not supported(deps.platform):
        print("[skip] background service: not supported on this platform yet. Run `herdr-lark run` in a terminal and keep it open.")
    elif _want_service(args, deps):
        if service_install(deps, dry_run=False) != 0:
            return 1
        service_running = True
    else:
        print("[skip] background service not installed. Run `herdr-lark service install` later, or `herdr-lark run` in a terminal.")

    owner = OwnerStore(owner_path()).read()
    if owner:
        print(f"[ok] already paired with {owner}. Run `herdr-lark unpair` to pair a different account.")
        return 0
    code = PairingStore(pairing_path()).arm(time.time()).code
    print()
    print(f"Pairing code: {code}")
    print(
        f"Open Lark, find your bot, and send it this code as a direct message within "
        f"{int(PAIRING_TTL_SECONDS // 60)} minutes. The sender becomes the only owner."
    )
    if not service_running:
        print("The bridge must be running to receive it: `herdr-lark run`.")
    return 0

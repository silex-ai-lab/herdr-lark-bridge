from __future__ import annotations

import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import service
from .config import ConfigError, Credentials, credentials_path, load_credentials, owner_path
from .deps import Deps
from .herdr import HerdrError
from .lark import LarkError
from .pairing import OwnerStore

CheckStatus = Literal["ok", "fail", "skip"]
LOG_TAIL_LINES = 20
ERROR_LINE = re.compile(r"\b(ERROR|CRITICAL)\b|Traceback")


@dataclass(frozen=True)
class Check:
    name: str
    status: CheckStatus
    detail: str
    fix: str = ""


def _herdr_checks(deps: Deps) -> list[Check]:
    binary = deps.find_herdr()
    if binary is None:
        return [
            Check("herdr binary", "fail", "not found on PATH or ~/.local/bin/herdr", "Install herdr (0.9.3 or newer) and make sure `herdr` is on PATH."),
            Check("herdr server", "skip", "needs the herdr binary"),
        ]
    found = Check("herdr binary", "ok", binary)
    try:
        n = len(deps.make_herdr().list_agents())
    except HerdrError as e:
        return [found, Check("herdr server", "fail", str(e), "Start herdr in a terminal, then rerun `herdr-lark doctor`.")]
    return [found, Check("herdr server", "ok", f"`herdr agent list` works, {n} agents")]


def _credential_checks(deps: Deps) -> list[Check]:
    path = credentials_path()
    try:
        creds = load_credentials()
    except ConfigError as e:
        return [
            Check("credentials", "fail", str(e), f"Run `herdr-lark setup`, or chmod 600 {path}."),
            Check("token fetch", "skip", "needs valid credentials"),
        ]
    mode = stat.S_IMODE(path.stat().st_mode)
    cred_check = Check("credentials", "ok", f"{path} mode {mode:04o}, domain {creds.domain}")
    return [cred_check, _token_check(deps, creds)]


def _token_check(deps: Deps, creds: Credentials) -> Check:
    try:
        deps.make_lark(creds).check_credentials()
    except LarkError as e:
        return Check("token fetch", "fail", str(e), "Check App ID, App Secret and domain, and that the app is published. Rerun `herdr-lark setup`.")
    return Check("token fetch", "ok", "tenant access token fetched")


def _owner_check() -> Check:
    owner = OwnerStore(owner_path()).read()
    if owner:
        return Check("owner paired", "ok", owner)
    return Check("owner paired", "fail", "no owner yet", "Run `herdr-lark pair`, then DM the code to the bot.")


def _service_checks(deps: Deps, home: Path) -> list[Check]:
    if not service.supported(deps.platform):
        return [
            Check("service", "skip", "launchd service is macOS only; use `herdr-lark run`"),
            Check("log tail", "skip", "no service log on this platform"),
        ]
    st = service.status(home, deps.launchctl)
    if st.state == "running":
        svc = Check("service", "ok", f"running (pid {st.pid})")
    elif st.state == "stopped":
        svc = Check("service", "fail", "installed but not running", "Run `herdr-lark service install` to reload it, then read the log.")
    else:
        svc = Check("service", "fail", "not installed", "Run `herdr-lark service install`, or `herdr-lark run` in a terminal.")
    return [svc, _log_check(home)]


def _log_check(home: Path) -> Check:
    logs = [service.stdout_log(home), service.stderr_log(home)]
    existing = [p for p in logs if p.exists()]
    if not existing:
        return Check("log tail", "skip", f"no log under {service.log_dir(home)} yet")
    bad: list[str] = []
    for p in existing:
        tail = p.read_text(errors="replace").splitlines()[-LOG_TAIL_LINES:]
        bad.extend(line for line in tail if ERROR_LINE.search(line))
    if bad:
        return Check("log tail", "fail", f"{len(bad)} error lines, last: {bad[-1][:200]}", f"Read {service.log_dir(home)}.")
    return Check("log tail", "ok", f"no errors in the last {LOG_TAIL_LINES} lines")


def run_checks(deps: Deps, home: Path) -> list[Check]:
    return [
        *_herdr_checks(deps),
        *_credential_checks(deps),
        _owner_check(),
        *_service_checks(deps, home),
    ]


def format_check(c: Check) -> str:
    line = f"[{c.status if c.status != 'fail' else 'FAIL'}] {c.name}: {c.detail}"
    return line + (f"\n       fix: {c.fix}" if c.status == "fail" and c.fix else "")


def run_doctor(deps: Deps, home: Path) -> int:
    checks = run_checks(deps, home)
    for c in checks:
        print(format_check(c))
    return 1 if any(c.status == "fail" for c in checks) else 0

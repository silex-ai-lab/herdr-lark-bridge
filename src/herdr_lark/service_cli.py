from __future__ import annotations

import os
import sys
from pathlib import Path

from . import service
from .deps import Deps


def service_install(deps: Deps, dry_run: bool) -> int:
    if not service.supported(deps.platform):
        print(service.UNSUPPORTED)
        return 0
    home = Path.home()
    herdr = deps.find_herdr()
    plist = service.render_plist(home, sys.executable, herdr, dict(os.environ))
    if dry_run:
        print(plist.decode(), end="")
        return 0
    if herdr is None:
        print("warning: herdr was not found on PATH. Install herdr, then rerun `herdr-lark service install`.")
    try:
        service.install(home, plist, deps.launchctl)
    except service.ServiceError as e:
        print(f"service install failed: {e}", file=sys.stderr)
        return 1
    print(f"service installed: {service.plist_path(home)}")
    print(f"logs: {service.log_dir(home)}")
    return 0


def service_uninstall(deps: Deps) -> int:
    if not service.supported(deps.platform):
        print(service.UNSUPPORTED)
        return 0
    removed = service.uninstall(Path.home(), deps.launchctl)
    print("service removed" if removed else "service was not installed")
    return 0


def service_status(deps: Deps) -> int:
    if not service.supported(deps.platform):
        print(service.UNSUPPORTED)
        return 0
    st = service.status(Path.home(), deps.launchctl)
    print(f"service: {st.state}" + (f" (pid {st.pid})" if st.pid else ""))
    return 0 if st.state == "running" else 1

from __future__ import annotations

import os
import plistlib
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Sequence

from .fsio import atomic_write

LABEL = "com.user.herdr-lark-bridge"
BASE_PATH = ("~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin")
PASSTHROUGH_ENV = ("HERDR_LARK_CONFIG_DIR", "HERDR_LARK_STATE_DIR", "HERDR_LARK_API_BASE")

Launchctl = Callable[[Sequence[str]], tuple[int, str]]
ServiceState = Literal["not-installed", "stopped", "running"]


class ServiceError(Exception):
    pass


@dataclass(frozen=True)
class ServiceStatus:
    state: ServiceState
    pid: int | None = None


def supported(platform: str) -> bool:
    return platform == "darwin"


def plist_path(home: Path) -> Path:
    return home / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def log_dir(home: Path) -> Path:
    return home / "Library" / "Logs" / "herdr-lark"


def stdout_log(home: Path) -> Path:
    return log_dir(home) / "bridge.log"


def stderr_log(home: Path) -> Path:
    return log_dir(home) / "bridge.err.log"


def service_path(home: Path, herdr_binary: str | None) -> str:
    dirs: list[str] = []
    if herdr_binary:
        dirs.append(str(Path(herdr_binary).parent))
    dirs.extend(d.replace("~", str(home), 1) for d in BASE_PATH)
    return ":".join(dict.fromkeys(dirs))


def render_plist(
    home: Path, python: str, herdr_binary: str | None, env: dict[str, str]
) -> bytes:
    environment = {"PATH": service_path(home, herdr_binary), "HOME": str(home)}
    environment.update({k: env[k] for k in PASSTHROUGH_ENV if env.get(k)})
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": [python, "-m", "herdr_lark.cli", "run"],
            "WorkingDirectory": str(home),
            "EnvironmentVariables": environment,
            "RunAtLoad": True,
            "KeepAlive": True,
            "ThrottleInterval": 10,
            "StandardOutPath": str(stdout_log(home)),
            "StandardErrorPath": str(stderr_log(home)),
        }
    )


def subprocess_launchctl(args: Sequence[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(["launchctl", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return p.returncode, (p.stdout + p.stderr).strip()


def _domain() -> str:
    return f"gui/{os.getuid()}"


def install(home: Path, plist: bytes, launchctl: Launchctl) -> None:
    target = plist_path(home)
    log_dir(home).mkdir(parents=True, exist_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, plist.decode(), mode=0o644)
    launchctl(("bootout", f"{_domain()}/{LABEL}"))
    code, out = launchctl(("bootstrap", _domain(), str(target)))
    if code != 0:
        raise ServiceError(f"launchctl bootstrap failed: {out}")
    launchctl(("kickstart", "-k", f"{_domain()}/{LABEL}"))


def uninstall(home: Path, launchctl: Launchctl) -> bool:
    launchctl(("bootout", f"{_domain()}/{LABEL}"))
    target = plist_path(home)
    existed = target.exists()
    target.unlink(missing_ok=True)
    return existed


def status(home: Path, launchctl: Launchctl) -> ServiceStatus:
    if not plist_path(home).exists():
        return ServiceStatus("not-installed")
    code, out = launchctl(("print", f"{_domain()}/{LABEL}"))
    if code != 0:
        return ServiceStatus("stopped")
    pid = re.search(r"^\s*pid = (\d+)", out, re.MULTILINE)
    if pid and re.search(r"^\s*state = running", out, re.MULTILINE):
        return ServiceStatus("running", int(pid.group(1)))
    return ServiceStatus("stopped")


UNSUPPORTED = (
    "The background service is only supported on macOS (launchd) for now. "
    "Run `herdr-lark run` in the foreground instead."
)

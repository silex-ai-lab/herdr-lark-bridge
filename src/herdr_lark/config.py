from __future__ import annotations

import os
import stat
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

from .models import Config


class ConfigError(Exception):
    pass


def config_dir() -> Path:
    return Path(os.environ.get("HERDR_LARK_CONFIG_DIR", "~/.config/herdr-lark")).expanduser()


def state_path() -> Path:
    base = Path(os.environ.get("HERDR_LARK_STATE_DIR", "~/.local/state/herdr-lark")).expanduser()
    return base / "state.json"


def load_config(path: Path | None = None) -> Config:
    path = path or config_dir() / "config.toml"
    try:
        data = tomllib.loads(path.read_text())
    except FileNotFoundError:
        return Config()
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    allowed = sorted(f.name for f in fields(Config))
    unknown = set(data) - set(allowed)
    if unknown:
        raise ConfigError(f"{path}: unknown keys {sorted(unknown)}; allowed {allowed}")
    for k, v in data.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0:
            raise ConfigError(f"{path}: {k} must be a non-negative number")
    d = Config()
    return Config(
        poll_seconds=float(data.get("poll_seconds", d.poll_seconds)),
        blocked_delay_seconds=float(data.get("blocked_delay_seconds", d.blocked_delay_seconds)),
        done_delay_seconds=float(data.get("done_delay_seconds", d.done_delay_seconds)),
        screen_lines=int(data.get("screen_lines", d.screen_lines)),
        read_lines=int(data.get("read_lines", d.read_lines)),
    )


@dataclass(frozen=True)
class Credentials:
    app_id: str
    app_secret: str


def load_credentials(path: Path | None = None) -> Credentials:
    path = path or config_dir() / "credentials.env"
    try:
        st = path.stat()
    except FileNotFoundError:
        raise ConfigError(
            f"{path} not found. Create it with LARK_APP_ID and LARK_APP_SECRET and chmod 600."
        ) from None
    if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ConfigError(
            f"{path} has mode {stat.S_IMODE(st.st_mode):04o}; refusing to start. Run: chmod 600 {path}"
        )
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip("'\"")
    missing = [k for k in ("LARK_APP_ID", "LARK_APP_SECRET") if not env.get(k)]
    if missing:
        raise ConfigError(f"{path} is missing {', '.join(missing)}")
    return Credentials(env["LARK_APP_ID"], env["LARK_APP_SECRET"])

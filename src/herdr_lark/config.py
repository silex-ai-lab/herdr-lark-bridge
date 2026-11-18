from __future__ import annotations

import os
import stat
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

from .fsio import atomic_write
from .models import DOMAINS, LANGS, Config, Domain, Lang


class ConfigError(Exception):
    pass


def config_dir() -> Path:
    return Path(os.environ.get("HERDR_LARK_CONFIG_DIR", "~/.config/herdr-lark")).expanduser()


def state_path() -> Path:
    base = Path(os.environ.get("HERDR_LARK_STATE_DIR", "~/.local/state/herdr-lark")).expanduser()
    return base / "state.json"


def owner_path() -> Path:
    return config_dir() / "owner"


def pairing_path() -> Path:
    return config_dir() / "pairing.json"


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
    lang = data.pop("lang", None)
    if lang is not None and lang not in LANGS:
        raise ConfigError(f"{path}: lang must be one of {list(LANGS)}")
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
        shortcut_minutes=float(data.get("shortcut_minutes", d.shortcut_minutes)),
        max_inbound_age_seconds=float(
            data.get("max_inbound_age_seconds", d.max_inbound_age_seconds)
        ),
        prune_after_seconds=float(data.get("prune_after_seconds", d.prune_after_seconds)),
        lang=parse_lang(lang) if lang is not None else d.lang,
    )


def parse_lang(raw: str) -> Lang:
    for lang in LANGS:
        if raw == lang:
            return lang
    raise ConfigError(f"lang must be one of {list(LANGS)}, got {raw!r}")


def parse_domain(raw: str) -> Domain:
    for domain in DOMAINS:
        if raw == domain:
            return domain
    raise ConfigError(f"LARK_DOMAIN must be one of {list(DOMAINS)}, got {raw!r}")


@dataclass(frozen=True)
class Credentials:
    app_id: str
    app_secret: str
    domain: Domain = "lark"


def credentials_path() -> Path:
    return config_dir() / "credentials.env"


def write_credentials(creds: Credentials, path: Path | None = None) -> Path:
    path = path or credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    atomic_write(
        path,
        f"LARK_DOMAIN={creds.domain}\nLARK_APP_ID={creds.app_id}\nLARK_APP_SECRET={creds.app_secret}\n",
    )
    return path


def load_credentials(path: Path | None = None) -> Credentials:
    path = path or credentials_path()
    try:
        st = path.stat()
    except FileNotFoundError:
        raise ConfigError(
            f"{path} not found. Run `herdr-lark setup`."
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
    return Credentials(
        env["LARK_APP_ID"], env["LARK_APP_SECRET"], parse_domain(env.get("LARK_DOMAIN", "lark"))
    )

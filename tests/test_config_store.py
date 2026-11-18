import os
from pathlib import Path

import pytest

from herdr_lark.config import ConfigError, load_config, load_credentials
from herdr_lark.models import Attention, MessageRef, State
from herdr_lark.store import StateStore


def test_credentials_refuse_loose_mode(tmp_path: Path):
    p = tmp_path / "credentials.env"
    p.write_text("LARK_APP_ID=a\nLARK_APP_SECRET=b\n")
    p.chmod(0o644)
    with pytest.raises(ConfigError, match="chmod 600"):
        load_credentials(p)
    p.chmod(0o600)
    c = load_credentials(p)
    assert (c.app_id, c.app_secret) == ("a", "b")


def test_credentials_missing_key(tmp_path: Path):
    p = tmp_path / "c.env"
    p.write_text("LARK_APP_ID=a\n")
    p.chmod(0o600)
    with pytest.raises(ConfigError, match="LARK_APP_SECRET"):
        load_credentials(p)


def test_config_defaults_overrides_and_unknown_key(tmp_path: Path):
    assert load_config(tmp_path / "none.toml").poll_seconds == 3.0
    p = tmp_path / "config.toml"
    p.write_text("blocked_delay_seconds = 5\nscreen_lines = 10\n")
    c = load_config(p)
    assert (c.blocked_delay_seconds, c.screen_lines, c.done_delay_seconds) == (5.0, 10, 60.0)
    p.write_text("bogus = 1\n")
    with pytest.raises(ConfigError, match="bogus"):
        load_config(p)


def test_store_roundtrip_and_no_temp_left(tmp_path: Path):
    store = StateStore(tmp_path / "sub" / "state.json")
    assert store.load() == State()
    st = State(
        owner_open_id="ou_1",
        baselined=True,
        pending={("t", "blocked"): Attention("blocked", "t", 3, 12.5)},
        notified={"t": {"blocked": 3}},
        messages={"om": MessageRef("t", "blocked", 3)},
        seen_events=("e",),
    )
    store.save(st)
    assert store.load() == st
    assert os.listdir(tmp_path / "sub") == ["state.json"]

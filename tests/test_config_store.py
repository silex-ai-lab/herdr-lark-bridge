import json
import os
import stat
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
    assert (c.shortcut_minutes, c.max_inbound_age_seconds, c.prune_after_seconds) == (30.0, 120.0, 600.0)
    p.write_text("shortcut_minutes = 5\nmax_inbound_age_seconds = 9\nprune_after_seconds = 7\n")
    c = load_config(p)
    assert (c.shortcut_minutes, c.max_inbound_age_seconds, c.prune_after_seconds) == (5.0, 9.0, 7.0)
    p.write_text("bogus = 1\n")
    with pytest.raises(ConfigError, match="bogus"):
        load_config(p)


def test_store_roundtrip_and_no_temp_left(tmp_path: Path):
    store = StateStore(tmp_path / "sub" / "state.json")
    assert store.load() == State()
    st = State(
        pending={("t", "blocked"): Attention("blocked", "t", 3, 12.5)},
        notified={"t": {"blocked": 3}},
        messages={"om": MessageRef("t", "blocked", 3, "abc", 99.5)},
        last_seen={"t": 12.5},
        seen_events=("e",),
    )
    store.save(st)
    assert store.load() == st
    assert os.listdir(tmp_path / "sub") == ["state.json"]


def test_state_dir_is_0700_and_file_0600(tmp_path: Path):
    path = tmp_path / "new" / "state.json"
    StateStore(path).save(State())
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_missing_state_file_starts_fresh_without_creating_anything(tmp_path: Path):
    assert StateStore(tmp_path / "state.json").load() == State()
    assert os.listdir(tmp_path) == []


@pytest.mark.parametrize("junk", ["{not json", "[]", '{"pending": [{"kind": "blocked"}]}', ""])
def test_corrupt_state_is_moved_aside_and_load_starts_fresh(tmp_path: Path, junk: str):
    path = tmp_path / "state.json"
    path.write_text(junk)
    assert StateStore(path).load() == State()
    assert not path.exists()
    asides = [p for p in os.listdir(tmp_path) if p.startswith("state.json.corrupt-")]
    assert len(asides) == 1
    assert (tmp_path / asides[0]).read_text() == junk


def test_legacy_state_with_owner_and_pairing_keys_loads_and_drops_them(tmp_path: Path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "owner_open_id": "ou_old", "pairing_code": "123456", "pair_failures": 2,
        "baselined": True, "notified": {"t": {"done": 4}},
        "messages": {"om": {"terminal_id": "t", "kind": "blocked", "seq": 3}},
    }))
    store = StateStore(path)
    st = store.load()
    assert st.notified == {"t": {"done": 4}}
    assert st.messages["om"] == MessageRef("t", "blocked", 3, None, 0.0)
    store.save(st)
    saved = json.loads(path.read_text())
    assert not {"owner_open_id", "pairing_code", "pair_failures", "baselined"} & set(saved)

import stat
from pathlib import Path

import pytest

from herdr_lark.cli import main
from herdr_lark.pairing import OwnerStore, PairingStore


@pytest.fixture(autouse=True)
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HERDR_LARK_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("HERDR_LARK_STATE_DIR", str(tmp_path / "state"))
    return tmp_path


def test_pair_arms_and_prints_a_code_that_matches_the_file(dirs: Path, capsys: pytest.CaptureFixture[str]):
    assert main(["pair"]) == 0
    code = capsys.readouterr().out.strip()
    armed = PairingStore(dirs / "cfg" / "pairing.json")
    p = armed.load()
    assert p is not None and p.code == code and len(code) == 6
    assert stat.S_IMODE(armed.path.stat().st_mode) == 0o600


def test_pair_refuses_when_owner_exists_and_unpair_removes_owner(dirs: Path):
    owner = OwnerStore(dirs / "cfg" / "owner")
    owner.write("ou_1")
    assert main(["pair"]) == 1
    assert not (dirs / "cfg" / "pairing.json").exists()
    assert main(["unpair"]) == 0
    assert owner.read() is None
    assert main(["pair"]) == 0


def test_pair_code_subcommand_is_gone():
    with pytest.raises(SystemExit):
        main(["pair-code"])


def test_run_without_credentials_refuses_cleanly(dirs: Path, capsys: pytest.CaptureFixture[str]):
    assert main(["run"]) == 2
    assert "credentials.env" in capsys.readouterr().err

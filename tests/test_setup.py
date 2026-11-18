import stat
from pathlib import Path

import pytest

from herdr_lark.cli import main
from herdr_lark.config import Credentials, load_credentials
from herdr_lark.pairing import OwnerStore, PairingStore

from deps_fakes import DepsRig


@pytest.fixture(autouse=True)
def dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HERDR_LARK_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("HERDR_LARK_STATE_DIR", str(tmp_path / "state"))
    for k in ("LARK_APP_ID", "LARK_APP_SECRET", "LARK_DOMAIN"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


NON_INTERACTIVE = ["setup", "--non-interactive", "--app-id", "cli_a", "--no-service"]


def test_non_interactive_setup_saves_verifies_and_arms_pairing(
    dirs: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv("LARK_APP_SECRET", "s3cret")
    rig = DepsRig()
    assert main(NON_INTERACTIVE, rig.deps) == 0
    out = capsys.readouterr().out
    cred = dirs / "cfg" / "credentials.env"
    assert stat.S_IMODE(cred.stat().st_mode) == 0o600
    assert load_credentials() == Credentials("cli_a", "s3cret", "lark")
    assert rig.lark.checks == 1 and rig.launchctl.calls == []
    code = PairingStore(dirs / "cfg" / "pairing.json").load()
    assert code is not None
    assert f"Pairing code: {code.code}" in out and "direct message" in out
    assert "[ok] credentials verified" in out


def test_feishu_domain_reaches_the_client_and_the_file(dirs: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LARK_APP_SECRET", "s")
    rig = DepsRig()
    assert main([*NON_INTERACTIVE, "--domain", "feishu"], rig.deps) == 0
    assert rig.made_for[-1].domain == "feishu"
    assert "LARK_DOMAIN=feishu" in (dirs / "cfg" / "credentials.env").read_text()


def test_domain_and_ids_can_come_from_env(dirs: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LARK_APP_ID", "cli_env")
    monkeypatch.setenv("LARK_APP_SECRET", "s")
    monkeypatch.setenv("LARK_DOMAIN", "feishu")
    rig = DepsRig()
    assert main(["setup", "--non-interactive", "--no-service"], rig.deps) == 0
    assert load_credentials() == Credentials("cli_env", "s", "feishu")


def test_failed_verification_prints_fail_and_stops_before_service_and_pairing(
    dirs: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv("LARK_APP_SECRET", "wrong")
    rig = DepsRig(lark_error="code=10003 msg=invalid app secret")
    assert main(["setup", "--non-interactive", "--app-id", "cli_a", "--service"], rig.deps) == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out and "invalid app secret" in out and "rerun `herdr-lark setup`" in out
    assert rig.launchctl.calls == []
    assert not (dirs / "cfg" / "pairing.json").exists()


def test_missing_values_in_non_interactive_mode_exit_2(capsys: pytest.CaptureFixture[str]):
    assert main(["setup", "--non-interactive"], DepsRig().deps) == 2
    assert "--app-id" in capsys.readouterr().err


def test_secret_can_be_read_from_stdin(
    dirs: Path, monkeypatch: pytest.MonkeyPatch
):
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("from-stdin\n"))
    assert main([*NON_INTERACTIVE, "--app-secret-stdin"], DepsRig().deps) == 0
    assert load_credentials().app_secret == "from-stdin"


def test_rerun_keeps_the_owner_and_does_not_arm_pairing_again(
    dirs: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv("LARK_APP_SECRET", "s")
    OwnerStore(dirs / "cfg" / "owner").write("ou_1")
    assert main(NON_INTERACTIVE, DepsRig().deps) == 0
    assert not (dirs / "cfg" / "pairing.json").exists()
    assert "already paired" in capsys.readouterr().out


def test_two_runs_converge_to_the_same_credentials(dirs: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LARK_APP_SECRET", "s")
    main(NON_INTERACTIVE, DepsRig().deps)
    first = (dirs / "cfg" / "credentials.env").read_text()
    main(NON_INTERACTIVE, DepsRig().deps)
    assert (dirs / "cfg" / "credentials.env").read_text() == first


def test_interactive_prompts_for_domain_id_secret_and_installs_the_service(dirs: Path):
    rig = DepsRig(answers=["feishu", "cli_i", "y"], secrets=["hidden"])
    assert main(["setup"], rig.deps) == 0
    assert load_credentials() == Credentials("cli_i", "hidden", "feishu")
    assert [c[0] for c in rig.launchctl.calls][:3] == ["bootout", "bootstrap", "kickstart"]
    assert any("hidden" in p for p in rig.prompts)


def test_interactive_reprompts_on_bad_domain_and_defaults_to_lark(dirs: Path):
    rig = DepsRig(answers=["china", "", "cli_i", "n"], secrets=["s"])
    assert main(["setup"], rig.deps) == 0
    assert load_credentials().domain == "lark"
    assert rig.launchctl.calls == []


def test_interactive_rerun_accepts_saved_values_with_enter(dirs: Path):
    main(["setup"], DepsRig(answers=["lark", "cli_i", "n"], secrets=["s1"]).deps)
    rig = DepsRig(answers=["", "", "n"], secrets=[""])
    assert main(["setup"], rig.deps) == 0
    assert load_credentials() == Credentials("cli_i", "s1", "lark")


def test_unsupported_platform_skips_the_service_and_still_pairs(
    dirs: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv("LARK_APP_SECRET", "s")
    rig = DepsRig(platform="linux")
    assert main(["setup", "--non-interactive", "--app-id", "a"], rig.deps) == 0
    out = capsys.readouterr().out
    assert "herdr-lark run" in out and "Pairing code:" in out
    assert rig.launchctl.calls == []

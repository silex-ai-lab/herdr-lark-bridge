import plistlib
import sys
from pathlib import Path

import pytest

from herdr_lark import service
from herdr_lark.cli import main

from deps_fakes import DepsRig
from helpers import FakeLaunchctl


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.delenv("HERDR_LARK_CONFIG_DIR", raising=False)
    monkeypatch.delenv("HERDR_LARK_STATE_DIR", raising=False)
    return h


def test_plist_fields(home: Path):
    d = plistlib.loads(service.render_plist(home, "/py/bin/python", "/opt/fake/bin/herdr", {}))
    assert d["Label"] == service.LABEL
    assert d["ProgramArguments"] == ["/py/bin/python", "-m", "herdr_lark.cli", "run"]
    assert d["RunAtLoad"] is True and d["KeepAlive"] is True
    assert d["EnvironmentVariables"]["HOME"] == str(home)
    assert d["StandardOutPath"] == str(home / "Library/Logs/herdr-lark/bridge.log")
    assert d["StandardErrorPath"] == str(home / "Library/Logs/herdr-lark/bridge.err.log")


def test_path_starts_with_the_herdr_directory_without_duplicates(home: Path):
    path = plistlib.loads(service.render_plist(home, "py", "/usr/local/bin/herdr", {}))[
        "EnvironmentVariables"
    ]["PATH"].split(":")
    assert path[0] == "/usr/local/bin"
    assert len(path) == len(set(path))
    assert str(home / ".local/bin") in path


def test_path_without_herdr_still_has_defaults(home: Path):
    path = plistlib.loads(service.render_plist(home, "py", None, {}))["EnvironmentVariables"]["PATH"]
    assert "/opt/homebrew/bin" in path.split(":")


def test_directory_overrides_are_carried_into_the_service(home: Path):
    env = {"HERDR_LARK_CONFIG_DIR": "/c", "HERDR_LARK_STATE_DIR": "/s", "OTHER": "x"}
    e = plistlib.loads(service.render_plist(home, "py", None, env))["EnvironmentVariables"]
    assert e["HERDR_LARK_CONFIG_DIR"] == "/c" and e["HERDR_LARK_STATE_DIR"] == "/s"
    assert "OTHER" not in e


def test_install_writes_plist_and_loads_it_idempotently(home: Path):
    lc = FakeLaunchctl()
    plist = service.render_plist(home, "py", None, {})
    service.install(home, plist, lc)
    service.install(home, plist, lc)
    assert plistlib.loads(service.plist_path(home).read_bytes())["Label"] == service.LABEL
    verbs = [c[0] for c in lc.calls]
    assert verbs == ["bootout", "bootstrap", "kickstart"] * 2
    assert service.log_dir(home).is_dir()


def test_install_reports_bootstrap_failure(home: Path):
    lc = FakeLaunchctl()
    lc.bootstrap_code = 5
    with pytest.raises(service.ServiceError, match="boom"):
        service.install(home, service.render_plist(home, "py", None, {}), lc, sleep=lambda _: None)


def test_install_retries_bootstrap_while_the_old_job_is_still_unloading(home: Path):
    codes = iter([5, 5, 0])

    class Slow(FakeLaunchctl):
        def __call__(self, args):  # type: ignore[no-untyped-def]
            code, out = super().__call__(args)
            return (next(codes), "Input/output error") if args[0] == "bootstrap" else (code, out)

    lc = Slow()
    service.install(home, service.render_plist(home, "py", None, {}), lc, sleep=lambda _: None)
    assert [c[0] for c in lc.calls] == ["bootout", "bootstrap", "bootstrap", "bootstrap", "kickstart"]


def test_uninstall_is_idempotent(home: Path):
    lc = FakeLaunchctl()
    service.install(home, service.render_plist(home, "py", None, {}), lc)
    assert service.uninstall(home, lc) is True
    assert service.uninstall(home, lc) is False
    assert not service.plist_path(home).exists()


RUNNING = "gui/501/x = {\n\tstate = running\n\tpid = 4242\n}"


def test_status_states(home: Path):
    assert service.status(home, FakeLaunchctl()).state == "not-installed"
    service.install(home, service.render_plist(home, "py", None, {}), FakeLaunchctl())
    assert service.status(home, FakeLaunchctl(RUNNING)) == service.ServiceStatus("running", 4242)
    assert service.status(home, FakeLaunchctl("state = waiting")).state == "stopped"
    assert service.status(home, FakeLaunchctl("", print_code=113)).state == "stopped"


def test_dry_run_prints_the_plist_and_touches_nothing(
    home: Path, capsys: pytest.CaptureFixture[str]
):
    rig = DepsRig()
    assert main(["service", "install", "--dry-run"], rig.deps) == 0
    out = capsys.readouterr().out
    d = plistlib.loads(out.encode())
    assert d["ProgramArguments"][0] == sys.executable
    assert d["EnvironmentVariables"]["PATH"].startswith("/opt/fake/bin:")
    assert rig.launchctl.calls == [] and not (home / "Library").exists()


def test_cli_install_status_uninstall(home: Path, capsys: pytest.CaptureFixture[str]):
    rig = DepsRig(launchctl=FakeLaunchctl(RUNNING))
    assert main(["service", "install"], rig.deps) == 0
    assert service.plist_path(home).exists()
    assert main(["service", "status"], rig.deps) == 0
    assert "running (pid 4242)" in capsys.readouterr().out
    assert main(["service", "uninstall"], rig.deps) == 0
    assert not service.plist_path(home).exists()


@pytest.mark.parametrize("action", ["install", "uninstall", "status"])
def test_other_platforms_say_unsupported_and_do_nothing(
    home: Path, capsys: pytest.CaptureFixture[str], action: str
):
    rig = DepsRig(platform="linux")
    assert main(["service", action], rig.deps) == 0
    out = capsys.readouterr().out
    assert "herdr-lark run" in out and "macOS" in out
    assert rig.launchctl.calls == [] and not (home / "Library").exists()

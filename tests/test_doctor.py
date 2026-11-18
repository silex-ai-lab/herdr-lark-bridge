from pathlib import Path

import pytest

from herdr_lark import service
from herdr_lark.cli import main
from herdr_lark.config import Credentials, write_credentials
from herdr_lark.doctor import run_checks
from herdr_lark.pairing import OwnerStore

from deps_fakes import DepsRig
from helpers import FakeLaunchctl

RUNNING = "state = running\npid = 7"


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("HERDR_LARK_CONFIG_DIR", str(tmp_path / "cfg"))
    return tmp_path


def healthy(env: Path) -> DepsRig:
    write_credentials(Credentials("cli_a", "s"))
    OwnerStore(env / "cfg" / "owner").write("ou_1")
    home = env / "home"
    rig = DepsRig(launchctl=FakeLaunchctl(RUNNING))
    service.install(home, service.render_plist(home, "py", None, {}), rig.launchctl)
    return rig


def statuses(rig: DepsRig, env: Path) -> dict[str, str]:
    return {c.name: c.status for c in run_checks(rig.deps, env / "home")}


def test_healthy_install_passes_every_check_and_exits_zero(
    env: Path, capsys: pytest.CaptureFixture[str]
):
    rig = healthy(env)
    assert main(["doctor"], rig.deps) == 0
    out = capsys.readouterr().out
    assert "[FAIL]" not in out and "[ok] service: running (pid 7)" in out


def test_fresh_machine_fails_with_fix_hints(env: Path, capsys: pytest.CaptureFixture[str]):
    rig = DepsRig(herdr_binary=None)
    assert main(["doctor"], rig.deps) == 1
    out = capsys.readouterr().out
    for name in ("herdr binary", "credentials", "owner paired", "service"):
        assert f"[FAIL] {name}" in out
    assert out.count("fix:") == 4
    assert "herdr-lark setup" in out


def test_credentials_with_loose_mode_fail(env: Path):
    rig = healthy(env)
    (env / "cfg" / "credentials.env").chmod(0o644)
    s = statuses(rig, env)
    assert s["credentials"] == "fail" and s["token fetch"] == "skip"


def test_token_failure_is_reported(env: Path):
    rig = healthy(env)
    rig.lark.error = "code=10003 msg=bad"
    assert statuses(rig, env)["token fetch"] == "fail"


def test_unreachable_herdr_server_fails(env: Path):
    rig = healthy(env)
    rig.herdr.down = True
    s = statuses(rig, env)
    assert s["herdr binary"] == "ok" and s["herdr server"] == "fail"


def test_stopped_service_fails(env: Path):
    rig = healthy(env)
    rig.launchctl.print_code = 113
    assert statuses(rig, env)["service"] == "fail"


def test_error_lines_in_the_log_tail_fail(env: Path):
    rig = healthy(env)
    service.stderr_log(env / "home").write_text(
        "2026-01-01 INFO x ok\n2026-01-01 ERROR herdr_lark.daemon engine step failed\n"
    )
    assert statuses(rig, env)["log tail"] == "fail"


def test_old_errors_beyond_the_tail_are_ignored(env: Path):
    rig = healthy(env)
    log = service.stderr_log(env / "home")
    log.write_text("ERROR old\n" + "INFO fine\n" * 30)
    assert statuses(rig, env)["log tail"] == "ok"


def test_warnings_are_not_errors(env: Path):
    rig = healthy(env)
    service.stderr_log(env / "home").write_text("2026 WARNING herdr unavailable\n")
    assert statuses(rig, env)["log tail"] == "ok"


def test_linux_skips_service_checks_and_can_still_pass(env: Path, capsys: pytest.CaptureFixture[str]):
    write_credentials(Credentials("cli_a", "s"))
    OwnerStore(env / "cfg" / "owner").write("ou_1")
    rig = DepsRig(platform="linux")
    assert main(["doctor"], rig.deps) == 0
    assert "[skip] service" in capsys.readouterr().out

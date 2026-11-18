import shutil

import pytest

from herdr_lark.herdr import HerdrCli, HerdrError, parse_agent_list


class FakeRunner:
    def __init__(self) -> None:
        self.argv: list[tuple[str, ...]] = []

    def __call__(self, args: tuple[str, ...]) -> str:
        self.argv.append(args)
        return ""


def cli() -> tuple[HerdrCli, FakeRunner]:
    r = FakeRunner()
    return HerdrCli(runner=r), r


def test_prompt_argv_is_target_then_one_text_element():
    c, r = cli()
    c.prompt("w1:p1", "hello world")
    assert r.argv == [("agent", "prompt", "w1:p1", "hello world")]


@pytest.mark.parametrize("text", ["--wait", "--timeout 5", "--until idle", "-x", "-- hi"])
def test_option_looking_prompt_text_stays_one_argv_element_after_target(text: str):
    c, r = cli()
    c.prompt("w1:p1", text)
    assert r.argv == [("agent", "prompt", "w1:p1", text)]


def test_send_keys_argv_is_one_element_per_key():
    c, r = cli()
    c.send_keys("w1:p1", ("down", "enter"))
    assert r.argv == [("agent", "send-keys", "w1:p1", "down", "enter")]


@pytest.mark.parametrize("text", ["use option B", "--wait", "-n"])
def test_send_text_argv_is_pane_then_one_text_element(text: str):
    c, r = cli()
    c.send_text("w1:p1", text)
    assert r.argv == [("pane", "send-text", "w1:p1", text)]


def test_read_argv():
    c, r = cli()
    c.read("w1:p1", 200)
    assert r.argv == [(
        "agent", "read", "w1:p1", "--source", "recent", "--lines", "200", "--format", "text",
    )]


def test_read_visible_argv_has_no_line_count():
    c, r = cli()
    c.read_visible("w1:p1")
    assert r.argv == [("agent", "read", "w1:p1", "--source", "visible", "--format", "text")]


def test_done_agent_without_completion_seq_parses_as_none():
    raw = (
        '{"result":{"agents":[{"terminal_id":"t","pane_id":"p","workspace_id":"w",'
        '"agent_status":"working"}]}}'
    )
    assert parse_agent_list(raw, {})[0].completion_seq is None


@pytest.mark.skipif(shutil.which("herdr") is None, reason="herdr binary not installed")
@pytest.mark.parametrize("text", ["--timeout", "--until", "--wait"])
def test_real_herdr_parses_leading_option_text_as_the_prompt_text(text: str):
    try:
        HerdrCli().prompt("nonexistent_target_zz", text)
    except HerdrError as e:
        assert "agent_not_found" in str(e), str(e)
    else:
        pytest.fail("prompt to a nonexistent target must fail")

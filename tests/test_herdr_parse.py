from pathlib import Path

import pytest

from herdr_lark.herdr import HerdrError, parse_agent_list
from herdr_lark.render import tail_screen

FIX = Path(__file__).parent / "fixtures"


def test_parses_captured_real_agent_list():
    snaps = parse_agent_list((FIX / "agent_list.json").read_text(), {"w25": "Main"})
    assert len(snaps) == 3
    assert all(s.workspace_label == "Main" for s in snaps)
    unnamed = next(s for s in snaps if s.name is None)
    assert unnamed.display_name == f"claude {unnamed.pane_id}"
    named = next(s for s in snaps if s.name == "reviewer-codex")
    assert named.agent == "codex" and named.status == "idle"
    assert named.terminal_id.startswith("term_") and named.completion_seq == 1287


def test_label_falls_back_to_workspace_id():
    snaps = parse_agent_list((FIX / "agent_list.json").read_text(), {})
    assert snaps[0].workspace_label == "w25"


def test_garbage_raises_herdr_error():
    with pytest.raises(HerdrError):
        parse_agent_list("not json", {})
    with pytest.raises(HerdrError):
        parse_agent_list('{"result":{"agents":[{"pane_id":"p"}]}}', {})


def test_unknown_status_maps_to_unknown():
    raw = '{"result":{"agents":[{"terminal_id":"t","pane_id":"p","workspace_id":"w","agent_status":"weird"}]}}'
    assert parse_agent_list(raw, {})[0].status == "unknown"


def test_tail_screen_trims_padding_and_keeps_last_lines():
    raw = (FIX / "agent_read.txt").read_text()
    assert not tail_screen(raw, 40).endswith("\n")
    assert tail_screen("a\nb\nc\n\n\n", 2) == "b\nc"
    assert len(tail_screen("x" * 50_000, 40)) < 20_100


def test_tail_screen_keeps_answer_above_a_blank_gap():
    from herdr_lark.render import tail_screen

    raw = "⏺ READY-1\n" + "\n" * 45 + "─" * 200 + "\n❯\n" + "─" * 200 + "\n\n  status\n"
    out = tail_screen(raw, 8)
    assert out.splitlines() == ["⏺ READY-1", "", "─" * 24, "❯", "─" * 24, "", "  status"]

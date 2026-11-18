from dataclasses import replace

import pytest

from herdr_lark.models import (
    Action,
    AgentSnapshot,
    Config,
    Ignore,
    Inbound,
    Keys,
    MessageRef,
    Prompt,
    Read,
    Reply,
    State,
    Text,
)
from herdr_lark.messages import ZH
from herdr_lark.route import admit, owner_action

from helpers import snap

CFG = Config()
OWNER = "ou_owner"
NOW = 10_000.0
DG = "digest-1"


def msg(text: str, sender: str = OWNER, eid: str = "e1", parent: str | None = None,
        root: str | None = None, chat: str = "p2p", created: float | None = NOW) -> Inbound:
    return Inbound(eid, f"om_{eid}", sender, chat, text, parent, root, created)


def route(inbound: Inbound, state: State, snapshots: list[AgentSnapshot],
          now: float = NOW, cfg: Config = CFG) -> tuple[State, Action]:
    state, early = admit(inbound, OWNER, state, cfg, now)
    if early is not None:
        return state, early
    return state, owner_action(inbound, state, snapshots, cfg, now)


def ref(tid: str = "t1", kind: str = "blocked", seq: int = 4, digest: str | None = DG,
        sent: float = NOW - 60) -> MessageRef:
    return MessageRef(tid, kind, seq, digest if kind == "blocked" else None, sent)  # type: ignore[arg-type]


def owned(**kw: object) -> State:
    return replace(State(), **kw)  # type: ignore[arg-type]


def blocked_state(seq: int = 4) -> tuple[State, list[AgentSnapshot]]:
    s = snap("t1", "blocked", state_change_seq=seq)
    return owned(messages={"om_n1": ref("t1", "blocked", seq)}), [s]


def test_group_chat_is_ignored_before_anything_else_even_with_owner_id():
    st, act = route(msg("/list", chat="group"), owned(), [])
    assert isinstance(act, Ignore) and st.seen_events == ()


def test_non_owner_ignored_and_not_recorded_in_seen_events():
    st, act = route(msg("y", sender="ou_other"), owned(), [snap(status="blocked")])
    assert isinstance(act, Ignore) and st.seen_events == ()


def test_owner_event_is_recorded_and_redelivery_ignored():
    st, snaps = blocked_state()
    st, first = route(msg("y", parent="om_n1"), st, snaps)
    assert isinstance(first, Keys) and st.seen_events == ("e1",)
    _, second = route(msg("y", parent="om_n1"), st, snaps)
    assert isinstance(second, Ignore)


def test_reply_maps_to_notification_terminal_via_parent_or_root():
    a = snap("t1", "blocked", name="a", state_change_seq=4)
    b = snap("t2", "blocked", name="b", state_change_seq=9)
    st = owned(messages={
        "om_a": ref("t1", "blocked", 4, "da"),
        "om_b": ref("t2", "blocked", 9, "db"),
    })
    _, act = route(msg("y", parent="om_b"), st, [a, b])
    assert act == Keys(b.pane_id, ("y",), "db")
    _, act = route(msg("n", eid="e2", root="om_a"), st, [a, b])
    assert act == Keys(a.pane_id, ("n",), "da")


def test_reply_to_unknown_message_gets_reply():
    _, act = route(msg("y", parent="om_gone"), owned(), [])
    assert isinstance(act, Reply)


def test_single_outstanding_gets_non_reply_text():
    st, snaps = blocked_state()
    _, act = route(msg("2"), st, snaps)
    assert act == Keys(snaps[0].pane_id, ("2",), DG)


def test_ambiguous_lists_outstanding_and_help():
    a = snap("t1", "blocked", name="a", state_change_seq=4)
    b = snap("t2", "done", name="b", completion_seq=2)
    st = owned(messages={
        "om_a": ref("t1", "blocked", 4),
        "om_b": ref("t2", "done", 2),
    })
    _, act = route(msg("y"), st, [a, b])
    assert isinstance(act, Reply) and "a" in act.text and "b" in act.text and "/list" in act.text


def test_none_outstanding_replies_help():
    _, act = route(msg("hello"), owned(), [snap()])
    assert isinstance(act, Reply) and "/help" in act.text


def test_stale_blocked_wrong_seq_and_wrong_status():
    st, _ = blocked_state(seq=4)
    _, act = route(msg("y", parent="om_n1"), st, [snap("t1", "blocked", state_change_seq=5)])
    assert isinstance(act, Reply) and "状态已变化" in act.text
    _, act = route(msg("y", eid="e2", parent="om_n1"), st, [snap("t1", "working", state_change_seq=4)])
    assert isinstance(act, Reply) and "工作中" in act.text


def test_stale_done_wrong_seq_and_working():
    st = owned(messages={"om_d": ref("t1", "done", 3)})
    _, act = route(msg("next", parent="om_d"), st, [snap("t1", "done", completion_seq=4)])
    assert isinstance(act, Reply) and "状态已变化" in act.text
    _, act = route(msg("next", eid="e2", parent="om_d"), st, [snap("t1", "working", completion_seq=3)])
    assert isinstance(act, Reply) and "状态已变化" in act.text


def test_done_target_accepts_idle_or_done_with_same_seq_and_prompts():
    st = owned(messages={"om_d": ref("t1", "done", 3)})
    for i, status in enumerate(("idle", "done")):
        s = snap("t1", status, completion_seq=3)  # type: ignore[arg-type]
        _, act = route(msg("do the thing", eid=f"e{i}", parent="om_d"), st, [s])
        assert act == Prompt(s.pane_id, "do the thing")


def test_blocked_key_tokens_are_sent_as_keys_case_insensitively():
    st, snaps = blocked_state()
    _, act = route(msg("Down Down ENTER", parent="om_n1"), st, snaps)
    assert act == Keys(snaps[0].pane_id, ("down", "down", "enter"), DG)


@pytest.mark.parametrize("text", [
    "no", "不要", "y.", "yes", "是", "否", "yes please", "y maybe", "12", "1 enter please",
    "输入", "text", "texty", "ok",
])
def test_blocked_target_refuses_anything_that_is_not_keys_or_prefixed_text(text: str):
    st, snaps = blocked_state()
    _, act = route(msg(text, parent="om_n1"), st, snaps)
    assert act == Reply(ZH.blocked_usage)


@pytest.mark.parametrize("text, typed", [
    ("输入 use option B", "use option B"),
    ("TEXT Use Option B", "Use Option B"),
    ("text no", "no"),
    ("text /compact", "/compact"),
    ("text --wait", "--wait"),
    ("输入 1 enter", "1 enter"),
])
def test_blocked_prefix_types_the_rest_literally(text: str, typed: str):
    st, snaps = blocked_state()
    _, act = route(msg(text, parent="om_n1"), st, snaps)
    assert act == Text(snaps[0].pane_id, typed, DG)


def test_quoted_slash_command_on_blocked_target_runs_as_command_never_typed():
    st, snaps = blocked_state()
    _, act = route(msg("/list", parent="om_n1"), st, snaps)
    assert isinstance(act, Reply) and "label-w1 / alpha" in act.text
    _, act = route(msg("/to alpha rm -rf", eid="e2", parent="om_n1"), st, snaps)
    assert isinstance(act, Reply)


def test_quoted_slash_text_on_done_target_stays_literal():
    s = snap("t1", "done", completion_seq=3)
    st = owned(messages={"om_d": ref("t1", "done", 3)})
    _, act = route(msg("/compact", parent="om_d"), st, [s])
    assert act == Prompt(s.pane_id, "/compact")


def test_blocked_target_without_recorded_digest_sends_nothing():
    st = owned(messages={"om_n1": ref("t1", "blocked", 4, None)})
    _, act = route(msg("y", parent="om_n1"), st, [snap("t1", "blocked", state_change_seq=4)])
    assert isinstance(act, Reply) and "屏幕" in act.text


def test_shortcut_applies_only_within_shortcut_minutes():
    st, snaps = blocked_state()
    inside = NOW - CFG.shortcut_minutes * 60 + 1
    st = owned(messages={"om_n1": ref("t1", "blocked", 4, DG, inside)})
    _, act = route(msg("y"), st, snaps)
    assert isinstance(act, Keys)
    outside = NOW - CFG.shortcut_minutes * 60 - 1
    st = owned(messages={"om_n1": ref("t1", "blocked", 4, DG, outside)})
    _, act = route(msg("y", eid="e2"), st, snaps)
    assert isinstance(act, Reply) and "30" in act.text


def test_shortcut_age_limit_does_not_apply_to_quoted_replies():
    st = owned(messages={"om_n1": ref("t1", "blocked", 4, DG, NOW - 86_400)})
    s = snap("t1", "blocked", state_change_seq=4)
    _, act = route(msg("y", parent="om_n1"), st, [s])
    assert isinstance(act, Keys)


def test_inbound_older_than_max_age_is_not_executed_and_says_so():
    st, snaps = blocked_state()
    old = NOW - CFG.max_inbound_age_seconds - 1
    _, act = route(msg("y", parent="om_n1", created=old), st, snaps)
    assert isinstance(act, Reply) and "过晚" in act.text
    _, act = route(msg("/list", eid="e2", created=old), st, snaps)
    assert isinstance(act, Reply) and "过晚" in act.text


def test_inbound_without_create_time_is_not_executed():
    st, snaps = blocked_state()
    _, act = route(msg("y", parent="om_n1", created=None), st, snaps)
    assert isinstance(act, Reply) and "过晚" in act.text


def test_inbound_just_inside_max_age_is_executed():
    st = owned(messages={"om_n1": ref("t1", "blocked", 4, DG, sent=NOW - 500)})
    snaps = [snap("t1", "blocked", state_change_seq=4)]
    _, act = route(msg("y", parent="om_n1", created=NOW - CFG.max_inbound_age_seconds), st, snaps)
    assert isinstance(act, Keys)


def test_inbound_created_before_the_notification_it_would_act_on_is_not_executed():
    st = owned(messages={"om_n1": ref("t1", "blocked", 4, DG, sent=NOW - 10)})
    s = snap("t1", "blocked", state_change_seq=4)
    _, act = route(msg("y", parent="om_n1", created=NOW - 11), st, [s])
    assert isinstance(act, Reply) and "过晚" in act.text
    _, act = route(msg("y", eid="e2", created=NOW - 11), st, [s])
    assert isinstance(act, Reply) and "过晚" in act.text
    _, act = route(msg("y", eid="e3", created=NOW - 9), st, [s])
    assert isinstance(act, Keys)


def test_late_event_is_still_recorded_so_redelivery_is_ignored():
    st, snaps = blocked_state()
    old = NOW - 1000
    st, _ = route(msg("y", parent="om_n1", created=old), st, snaps)
    _, act = route(msg("y", parent="om_n1", created=old), st, snaps)
    assert isinstance(act, Ignore)


def agents():
    return [
        snap("t1", "idle", ws="w1", pane="w1:p1", name="alpha"),
        snap("t2", "working", ws="w1", pane="w1:p2", name="beta"),
        snap("t3", "done", ws="w2", pane="w2:p1", name=None),
    ]


def test_list_numbers_agents_with_workspace_name_status():
    _, act = route(msg("/list"), owned(), agents())
    assert isinstance(act, Reply)
    lines = act.text.splitlines()
    assert lines[0].startswith("1. label-w1 / alpha") and "空闲" in lines[0]
    assert "beta" in lines[1] and "工作中" in lines[1]
    assert "claude w2:p1" in lines[2] and "已完成" in lines[2]


def test_read_by_number_and_name():
    _, act = route(msg("/read 2"), owned(), agents())
    assert act == Read("w1:p2", CFG.read_lines)
    _, act = route(msg("/read ALPHA", eid="e2"), owned(), agents())
    assert act == Read("w1:p1", CFG.read_lines)
    _, act = route(msg("/read 9", eid="e3"), owned(), agents())
    assert isinstance(act, Reply)
    _, act = route(msg("/read", eid="e4"), owned(), agents())
    assert isinstance(act, Reply)


def test_to_prompts_idle_or_done_only():
    _, act = route(msg("/to alpha fix the bug now"), owned(), agents())
    assert act == Prompt("w1:p1", "fix the bug now")
    _, act = route(msg("/to 3 go", eid="e2"), owned(), agents())
    assert act == Prompt("w2:p1", "go")
    _, act = route(msg("/to beta go", eid="e3"), owned(), agents())
    assert isinstance(act, Reply) and "工作中" in act.text


def test_help_and_unknown_command():
    _, act = route(msg("/help"), owned(), [])
    assert isinstance(act, Reply) and "/list" in act.text
    _, act = route(msg("/nope", eid="e2"), owned(), [])
    assert isinstance(act, Reply) and "/nope" in act.text

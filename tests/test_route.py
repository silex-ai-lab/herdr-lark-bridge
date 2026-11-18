from dataclasses import replace

from herdr_lark.models import (
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
from herdr_lark.route import route

from helpers import snap

CFG = Config()
OWNER = "ou_owner"


def msg(text: str, sender: str = OWNER, eid: str = "e1", parent: str | None = None,
        root: str | None = None, chat: str = "p2p") -> Inbound:
    return Inbound(eid, f"om_{eid}", sender, chat, text, parent, root)


def owned(**kw: object) -> State:
    return replace(State(owner_open_id=OWNER, baselined=True), **kw)  # type: ignore[arg-type]


def blocked_state(seq: int = 4) -> tuple[State, list]:
    s = snap("t1", "blocked", state_change_seq=seq)
    st = owned(messages={"om_n1": MessageRef("t1", "blocked", seq)})
    return st, [s]


def test_pairing_binds_sender_on_matching_code():
    st, act = route(msg("123456", sender="ou_new"), State(pairing_code="123456"), [])
    assert st.owner_open_id == "ou_new" and st.pairing_code is None
    assert isinstance(act, Reply)


def test_pairing_wrong_code_ignored_and_rotates_after_five():
    st = State(pairing_code="123456")
    for i in range(4):
        st, act = route(msg("000000", sender="ou_x", eid=f"e{i}"), st, [])
        assert isinstance(act, Ignore) and st.owner_open_id is None and st.pairing_code
    st, act = route(msg("000000", sender="ou_x", eid="e9"), st, [])
    assert st.pairing_code is None and st.owner_open_id is None


def test_non_owner_ignored_after_pairing():
    st, act = route(msg("y", sender="ou_other"), owned(), [snap(status="blocked")])
    assert isinstance(act, Ignore)


def test_group_chat_ignored():
    _, act = route(msg("/list", chat="group"), owned(), [])
    assert isinstance(act, Ignore)


def test_redelivered_event_ignored():
    st, snaps = blocked_state()
    st, first = route(msg("y", parent="om_n1"), st, snaps)
    assert isinstance(first, Keys)
    _, second = route(msg("y", parent="om_n1"), st, snaps)
    assert isinstance(second, Ignore)


def test_reply_maps_to_notification_terminal_via_parent_or_root():
    a = snap("t1", "blocked", name="a", state_change_seq=4)
    b = snap("t2", "blocked", name="b", state_change_seq=9)
    st = owned(messages={
        "om_a": MessageRef("t1", "blocked", 4),
        "om_b": MessageRef("t2", "blocked", 9),
    })
    _, act = route(msg("y", parent="om_b"), st, [a, b])
    assert act == Keys(b.pane_id, ("y",))
    _, act = route(msg("n", eid="e2", root="om_a"), st, [a, b])
    assert act == Keys(a.pane_id, ("n",))


def test_reply_to_unknown_message_gets_reply():
    _, act = route(msg("y", parent="om_gone"), owned(), [])
    assert isinstance(act, Reply)


def test_single_outstanding_gets_non_reply_text():
    st, snaps = blocked_state()
    _, act = route(msg("2"), st, snaps)
    assert act == Keys(snaps[0].pane_id, ("2",))


def test_ambiguous_lists_outstanding_and_help():
    a = snap("t1", "blocked", name="a", state_change_seq=4)
    b = snap("t2", "done", name="b", completion_seq=2)
    st = owned(messages={
        "om_a": MessageRef("t1", "blocked", 4),
        "om_b": MessageRef("t2", "done", 2),
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
    st = owned(messages={"om_d": MessageRef("t1", "done", 3)})
    _, act = route(msg("next", parent="om_d"), st, [snap("t1", "done", completion_seq=4)])
    assert isinstance(act, Reply) and "状态已变化" in act.text
    _, act = route(msg("next", eid="e2", parent="om_d"), st, [snap("t1", "working", completion_seq=3)])
    assert isinstance(act, Reply) and "状态已变化" in act.text


def test_done_target_accepts_idle_or_done_with_same_seq_and_prompts():
    st = owned(messages={"om_d": MessageRef("t1", "done", 3)})
    for i, status in enumerate(("idle", "done")):
        s = snap("t1", status, completion_seq=3)  # type: ignore[arg-type]
        _, act = route(msg("do the thing", eid=f"e{i}", parent="om_d"), st, [s])
        assert act == Prompt(s.pane_id, "do the thing")


def test_blocked_key_tokens_vs_literal_text():
    st, snaps = blocked_state()
    pane = snaps[0].pane_id
    _, act = route(msg("Down Down ENTER", parent="om_n1"), st, snaps)
    assert act == Keys(pane, ("down", "down", "enter"))
    _, act = route(msg("yes please", eid="e2", parent="om_n1"), st, snaps)
    assert act == Text(pane, "yes please", then_enter=True)
    _, act = route(msg("y maybe", eid="e3", parent="om_n1"), st, snaps)
    assert act == Text(pane, "y maybe", then_enter=True)
    _, act = route(msg("12", eid="e4", parent="om_n1"), st, snaps)
    assert isinstance(act, Text)


def test_slash_text_in_reply_is_literal_not_command():
    s = snap("t1", "done", completion_seq=3)
    st = owned(messages={"om_d": MessageRef("t1", "done", 3)})
    _, act = route(msg("/compact", parent="om_d"), st, [s])
    assert act == Prompt(s.pane_id, "/compact")


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

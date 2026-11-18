from herdr_lark.decide import decide
from herdr_lark.models import Config, State, record_sent
from herdr_lark.store import state_from_json, state_to_json

from helpers import snap, with_status

CFG = Config(blocked_delay_seconds=20, done_delay_seconds=60)
READY = State(baselined=True)


def test_blocked_delay_not_elapsed():
    st, due = decide(READY, [snap(status="blocked")], 100.0, CFG)
    st, due = decide(st, [snap(status="blocked")], 119.0, CFG)
    assert due == []


def test_blocked_delay_elapsed_notifies_once_recorded():
    s = snap(status="blocked", state_change_seq=7)
    st, _ = decide(READY, [s], 100.0, CFG)
    st, due = decide(st, [s], 120.0, CFG)
    assert [(n.kind, n.seq) for n in due] == [("blocked", 7)]
    st = record_sent(st, due[0], "om_1")
    st, due = decide(st, [s], 500.0, CFG)
    assert due == []


def test_blocked_resolved_before_delay_resets_clock():
    s = snap(status="blocked", state_change_seq=7)
    st, _ = decide(READY, [s], 100.0, CFG)
    st, _ = decide(st, [with_status(s, "working", state_change_seq=8)], 110.0, CFG)
    s2 = with_status(s, "blocked", state_change_seq=9)
    st, due = decide(st, [s2], 125.0, CFG)
    assert due == []
    st, due = decide(st, [s2], 144.0, CFG)
    assert due == []
    st, due = decide(st, [s2], 145.0, CFG)
    assert [n.seq for n in due] == [9]


def test_done_suppressed_while_sibling_working_then_released():
    d = snap("t1", "done", completion_seq=3)
    sibling = snap("t2", "working", name="beta")
    st, _ = decide(READY, [d, sibling], 100.0, CFG)
    st, due = decide(st, [d, sibling], 400.0, CFG)
    assert due == []
    st, due = decide(st, [d, with_status(sibling, "idle")], 401.0, CFG)
    assert [(n.kind, n.seq) for n in due] == [("done", 3)]


def test_done_sibling_in_other_workspace_does_not_suppress():
    d = snap("t1", "done", ws="w1")
    other = snap("t2", "working", ws="w2")
    st, _ = decide(READY, [d, other], 100.0, CFG)
    st, due = decide(st, [d, other], 160.0, CFG)
    assert len(due) == 1


def test_done_delay_not_elapsed():
    d = snap(status="done")
    st, _ = decide(READY, [d], 100.0, CFG)
    _, due = decide(st, [d], 159.0, CFG)
    assert due == []


def test_no_duplicate_after_restart_with_persisted_state():
    s = snap(status="blocked", state_change_seq=7)
    st, _ = decide(READY, [s], 100.0, CFG)
    st, due = decide(st, [s], 125.0, CFG)
    st = record_sent(st, due[0], "om_1")
    restored = state_from_json(state_to_json(st))
    assert restored == st
    _, due = decide(restored, [s], 9999.0, CFG)
    assert due == []


def test_first_start_baselines_done_but_notifies_blocked():
    done = snap("t1", "done", completion_seq=5)
    blocked = snap("t2", "blocked", name="b", state_change_seq=2)
    st, _ = decide(State(), [done, blocked], 100.0, CFG)
    assert st.baselined
    st, due = decide(st, [done, blocked], 1000.0, CFG)
    assert [(n.snapshot.terminal_id, n.kind) for n in due] == [("t2", "blocked")]


def test_new_completion_after_baseline_notifies():
    done = snap(status="done", completion_seq=5)
    st, _ = decide(State(), [done], 100.0, CFG)
    nxt = with_status(done, "done", completion_seq=6)
    st, _ = decide(st, [nxt], 200.0, CFG)
    _, due = decide(st, [nxt], 260.0, CFG)
    assert [n.seq for n in due] == [6]


def test_vanished_terminals_are_pruned():
    s = snap(status="blocked")
    st, _ = decide(READY, [s], 100.0, CFG)
    st, due = decide(st, [s], 130.0, CFG)
    st = record_sent(st, due[0], "om_1")
    st, _ = decide(st, [], 140.0, CFG)
    assert not st.pending and not st.notified and not st.messages


def test_message_map_is_capped():
    s = snap(status="blocked")
    st = READY
    st, due = decide(st, [s], 100.0, CFG)
    st, due = decide(st, [s], 130.0, CFG)
    for i in range(300):
        st = record_sent(st, due[0], f"om_{i}")
    assert len(st.messages) == 200 and "om_299" in st.messages and "om_0" not in st.messages

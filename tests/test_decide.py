from herdr_lark.decide import decide
from dataclasses import replace

from herdr_lark.models import Config, Notification, State, record_sent
from herdr_lark.store import state_from_json, state_to_json

from helpers import snap, with_status

CFG = Config(blocked_delay_seconds=20, done_delay_seconds=60)
READY = State()


def test_blocked_delay_not_elapsed():
    st, due = decide(READY, [snap(status="blocked")], 100.0, CFG)
    st, due = decide(st, [snap(status="blocked")], 119.0, CFG)
    assert due == []


def test_blocked_delay_elapsed_notifies_once_recorded():
    s = snap(status="blocked", state_change_seq=7)
    st, _ = decide(READY, [s], 100.0, CFG)
    st, due = decide(st, [s], 120.0, CFG)
    assert [(n.kind, n.seq) for n in due] == [("blocked", 7)]
    st = record_sent(st, due[0], "om_1", None, 120.0)
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
    st, _ = decide(READY, [with_status(d, "working"), sibling], 90.0, CFG)
    st, _ = decide(st, [d, sibling], 100.0, CFG)
    st, due = decide(st, [d, sibling], 400.0, CFG)
    assert due == []
    st, due = decide(st, [d, with_status(sibling, "idle")], 401.0, CFG)
    assert [(n.kind, n.seq) for n in due] == [("done", 3)]


def test_done_sibling_in_other_workspace_does_not_suppress():
    d = snap("t1", "done", ws="w1")
    other = snap("t2", "working", ws="w2")
    st, _ = decide(READY, [with_status(d, "working"), other], 90.0, CFG)
    st, _ = decide(st, [d, other], 100.0, CFG)
    st, due = decide(st, [d, other], 160.0, CFG)
    assert len(due) == 1


def test_done_delay_not_elapsed():
    d = snap(status="done")
    st, _ = decide(READY, [with_status(d, "working")], 90.0, CFG)
    st, _ = decide(st, [d], 100.0, CFG)
    _, due = decide(st, [d], 159.0, CFG)
    assert due == []


def test_no_duplicate_after_restart_with_persisted_state():
    s = snap(status="blocked", state_change_seq=7)
    st, _ = decide(READY, [s], 100.0, CFG)
    st, due = decide(st, [s], 125.0, CFG)
    st = record_sent(st, due[0], "om_1", None, 120.0)
    restored = state_from_json(state_to_json(st))
    assert restored == st
    _, due = decide(restored, [s], 9999.0, CFG)
    assert due == []


def test_terminal_first_seen_done_is_baselined_but_blocked_notifies():
    done = snap("t1", "done", completion_seq=5)
    blocked = snap("t2", "blocked", name="b", state_change_seq=2)
    st, _ = decide(State(), [done, blocked], 100.0, CFG)
    assert st.notified["t1"] == {"done": 5}
    st, due = decide(st, [done, blocked], 1000.0, CFG)
    assert [(n.snapshot.terminal_id, n.kind) for n in due] == [("t2", "blocked")]


def test_terminal_appearing_later_already_done_is_baselined_not_announced():
    st, _ = decide(State(), [snap("t1", "idle")], 100.0, CFG)
    late = snap("t2", "done", name="late", completion_seq=9)
    st, _ = decide(st, [snap("t1", "idle"), late], 200.0, CFG)
    st, due = decide(st, [snap("t1", "idle"), late], 400.0, CFG)
    assert due == []


def test_terminal_seen_working_then_done_is_announced():
    w = snap("t1", "working", completion_seq=None)
    st, _ = decide(State(), [w], 100.0, CFG)
    d = with_status(w, "done", completion_seq=1)
    st, _ = decide(st, [d], 110.0, CFG)
    _, due = decide(st, [d], 171.0, CFG)
    assert [(n.kind, n.seq) for n in due] == [("done", 1)]


def test_lower_or_equal_completion_seq_is_not_announced_again():
    d = snap("t1", "working", completion_seq=5)
    st, _ = decide(State(), [d], 100.0, CFG)
    st = record_sent(st, Notification(with_status(d, "done"), "done", 5), "om_1", None, 100.0)
    older = with_status(d, "done", completion_seq=4)
    st, _ = decide(st, [older], 200.0, CFG)
    _, due = decide(st, [older], 300.0, CFG)
    assert due == []


def test_done_without_completion_seq_is_never_announced():
    w = snap("t1", "working", completion_seq=None)
    st, _ = decide(State(), [w], 100.0, CFG)
    d = with_status(w, "done", completion_seq=None)
    st, _ = decide(st, [d], 110.0, CFG)
    st, due = decide(st, [d], 1000.0, CFG)
    assert due == [] and ("t1", "done") not in st.pending


def test_new_completion_after_baseline_notifies():
    done = snap(status="done", completion_seq=5)
    st, _ = decide(State(), [done], 100.0, CFG)
    assert st.notified["t1"] == {"done": 5}
    nxt = with_status(done, "done", completion_seq=6)
    st, _ = decide(st, [nxt], 200.0, CFG)
    _, due = decide(st, [nxt], 260.0, CFG)
    assert [n.seq for n in due] == [6]


def sent_state() -> State:
    s = snap(status="blocked")
    st, _ = decide(READY, [s], 100.0, CFG)
    st, due = decide(st, [s], 130.0, CFG)
    return record_sent(st, due[0], "om_1", "dg", 130.0)


def test_one_empty_snapshot_does_not_wipe_dedup_state():
    st = sent_state()
    st, _ = decide(st, [], 140.0, CFG)
    assert st.notified and st.messages
    st, due = decide(st, [snap(status="blocked")], 150.0, CFG)
    assert due == []


def test_terminal_absent_longer_than_prune_after_is_pruned():
    st = sent_state()
    st, _ = decide(st, [], 140.0, CFG)
    st, _ = decide(st, [], 130.0 + CFG.prune_after_seconds - 1, CFG)
    assert st.notified and st.messages
    st, _ = decide(st, [], 130.0 + CFG.prune_after_seconds + 1, CFG)
    assert not st.pending and not st.notified and not st.messages and not st.last_seen


def test_reappearing_terminal_resets_absence_clock():
    st = sent_state()
    st, _ = decide(st, [], 140.0, CFG)
    st, _ = decide(st, [snap(status="blocked")], 600.0, CFG)
    st, _ = decide(st, [], 650.0, CFG)
    st, _ = decide(st, [], 600.0 + CFG.prune_after_seconds - 1, CFG)
    assert st.notified


def test_legacy_state_without_last_seen_prunes_only_after_the_window():
    st = replace(sent_state(), last_seen={})
    st, _ = decide(st, [], 200.0, CFG)
    assert st.notified
    st, _ = decide(st, [], 200.0 + CFG.prune_after_seconds + 1, CFG)
    assert not st.notified


def test_message_map_is_capped():
    s = snap(status="blocked")
    st = READY
    st, due = decide(st, [s], 100.0, CFG)
    st, due = decide(st, [s], 130.0, CFG)
    for i in range(300):
        st = record_sent(st, due[0], f"om_{i}", None, 1.0)
    assert len(st.messages) == 200 and "om_299" in st.messages and "om_0" not in st.messages

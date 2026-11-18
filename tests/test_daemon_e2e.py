import logging
from pathlib import Path

import pytest

from herdr_lark.daemon import Engine
from herdr_lark.models import Config, Inbound, NOTIFY_RETRY_SECONDS
from herdr_lark.pairing import OwnerStore, PairingStore
from herdr_lark.store import StateStore

from helpers import FakeHerdr, FakeLark, snap, with_status

CFG = Config(blocked_delay_seconds=20, done_delay_seconds=60)
OWNER = "ou_owner"


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.herdr, self.lark, self.clock = FakeHerdr(), FakeLark(), Clock()
        self.owner = OwnerStore(tmp_path / "cfg" / "owner")
        self.pairing = PairingStore(tmp_path / "cfg" / "pairing.json")
        self.store_path = tmp_path / "state" / "state.json"
        self.engine = self.restart()
        self._n = 0

    def restart(self) -> Engine:
        self.engine = Engine(
            self.herdr, self.lark, StateStore(self.store_path), CFG, self.owner, self.pairing, self.clock
        )
        return self.engine

    def dm(self, text: str, parent: str | None = None, sender: str = OWNER, chat: str = "p2p",
           created: float | None = None, eid: str | None = None) -> None:
        self._n += 1
        eid = eid or f"e{self._n}"
        self.engine.handle_inbound(Inbound(
            eid, f"om_{eid}", sender, chat, text, parent_id=parent,
            created_at=self.clock.t if created is None else created,
        ))

    def pair(self) -> None:
        code = self.pairing.arm(self.clock.t).code
        self.dm(code)
        assert self.owner.read() == OWNER
        assert "配对成功" in self.lark.replies[-1][1].text

    def last_reply(self) -> str:
        return self.lark.replies[-1][1].text


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def make_blocked(rig: Rig) -> str:
    a = snap("t1", "idle", ws="w1", pane="w1:p1", name="planner")
    rig.herdr.agents = [a]
    rig.pair()
    rig.herdr.agents = [with_status(a, "working", state_change_seq=2)]
    rig.clock.t += 5
    rig.engine.tick()
    rig.herdr.agents = [with_status(a, "blocked", state_change_seq=3)]
    rig.clock.t += 5
    rig.engine.tick()
    assert rig.lark.sent == []
    rig.clock.t += 21
    rig.herdr.screen = "Allow bash?\n1. Yes\n2. No\n\n"
    rig.engine.tick()
    assert len(rig.lark.sent) == 1
    return "om_sent_1"


def test_blocked_notification_reply_issues_herdr_keys(rig: Rig):
    notif = make_blocked(rig)
    out = rig.lark.sent[0][1]
    assert "label-w1" in out.text and "planner" in out.text and "等待审批" in out.text
    assert out.code == "Allow bash?\n1. Yes\n2. No"
    rig.clock.t += 30
    rig.engine.tick()
    assert len(rig.lark.sent) == 1

    rig.dm("1", parent=notif)
    assert rig.herdr.calls == [("keys", "w1:p1", "1")]
    assert rig.lark.replies[-1][0].startswith("om_e")

    a = rig.herdr.agents[0]
    rig.herdr.agents = [with_status(a, "working", state_change_seq=4)]
    rig.dm("1", parent=notif)
    assert rig.herdr.calls == [("keys", "w1:p1", "1")]
    assert "状态已变化" in rig.last_reply()


@pytest.mark.parametrize("text", ["no", "不要", "y.", "yes", "是", "/list"])
def test_blocked_quoted_non_key_replies_send_no_input(rig: Rig, text: str):
    notif = make_blocked(rig)
    rig.dm(text, parent=notif)
    assert rig.herdr.calls == []
    if text == "/list":
        assert "planner" in rig.last_reply()
    else:
        assert "未执行" in rig.last_reply()


def test_blocked_prefixed_text_types_then_enter(rig: Rig):
    notif = make_blocked(rig)
    rig.dm("输入 use option B", parent=notif)
    assert rig.herdr.calls == [("text", "w1:p1", "use option B"), ("keys", "w1:p1", "enter")]


def test_changed_dialog_sends_nothing_and_resends_screen_as_new_quotable_notification(rig: Rig):
    notif = make_blocked(rig)
    rig.herdr.screen = "Delete everything?\n1. Yes\n2. No\n\n"
    rig.dm("1", parent=notif)
    assert rig.herdr.calls == []
    assert len(rig.lark.sent) == 2
    fresh = rig.lark.sent[1][1]
    assert "对话框已变化" in fresh.text and fresh.code == "Delete everything?\n1. Yes\n2. No"
    assert "对话框已变化" in rig.last_reply()

    rig.dm("1", parent="om_sent_2")
    assert rig.herdr.calls == [("keys", "w1:p1", "1")]


def test_changed_dialog_old_notification_keeps_being_refused(rig: Rig):
    notif = make_blocked(rig)
    rig.herdr.screen = "Something else\n"
    rig.dm("1", parent=notif)
    rig.dm("2", parent=notif)
    assert rig.herdr.calls == []


def test_digest_is_persisted_so_a_restart_still_proves_the_same_dialog(rig: Rig):
    notif = make_blocked(rig)
    rig.restart()
    rig.dm("2", parent=notif)
    assert rig.herdr.calls == [("keys", "w1:p1", "2")]


def test_plain_dm_shortcut_works_once_then_expires(rig: Rig):
    make_blocked(rig)
    rig.dm("1")
    assert rig.herdr.calls == [("keys", "w1:p1", "1")]
    rig.clock.t += CFG.shortcut_minutes * 60 + 1
    rig.dm("2")
    assert rig.herdr.calls == [("keys", "w1:p1", "1")]


def test_late_delivered_reply_is_not_executed(rig: Rig):
    notif = make_blocked(rig)
    rig.clock.t += 500
    rig.dm("1", parent=notif, created=rig.clock.t - 400)
    assert rig.herdr.calls == [] and "过晚" in rig.last_reply()


def test_reply_created_before_the_notification_is_not_executed(rig: Rig):
    notif = make_blocked(rig)
    rig.dm("1", parent=notif, created=rig.clock.t - 1)
    assert rig.herdr.calls == [] and "过晚" in rig.last_reply()


def test_done_notification_prompt_and_restart_has_no_duplicate(rig: Rig):
    a = snap("t1", "working", pane="w1:p1", name="planner", completion_seq=1)
    rig.herdr.agents = [a]
    rig.pair()
    rig.engine.tick()
    rig.herdr.agents = [with_status(a, "done", completion_seq=2)]
    rig.engine.tick()
    rig.clock.t += 61
    rig.engine.tick()
    assert len(rig.lark.sent) == 1 and "已完成" in rig.lark.sent[0][1].text

    engine2 = rig.restart()
    rig.clock.t += 600
    engine2.tick()
    assert len(rig.lark.sent) == 1

    rig.dm("write tests", parent="om_sent_1")
    assert rig.herdr.calls == [("prompt", "w1:p1", "write tests")]


def test_one_empty_agent_list_does_not_cause_a_duplicate_notification(rig: Rig):
    a = snap("t1", "working", pane="w1:p1", name="p", completion_seq=1)
    rig.herdr.agents = [a]
    rig.pair()
    rig.engine.tick()
    rig.herdr.agents = [with_status(a, "done", completion_seq=2)]
    rig.engine.tick()
    rig.clock.t += 61
    rig.engine.tick()
    assert len(rig.lark.sent) == 1
    rig.herdr.agents = []
    rig.clock.t += 3
    rig.engine.tick()
    rig.herdr.agents = [with_status(a, "done", completion_seq=2)]
    rig.clock.t += 3
    rig.engine.tick()
    rig.clock.t += 300
    rig.engine.tick()
    assert len(rig.lark.sent) == 1


def test_done_without_completion_seq_warns_once_and_is_skipped(rig: Rig, caplog: pytest.LogCaptureFixture):
    a = snap("t1", "working", completion_seq=None)
    rig.herdr.agents = [a]
    rig.pair()
    rig.herdr.agents = [with_status(a, "done", completion_seq=None)]
    with caplog.at_level(logging.WARNING):
        for _ in range(4):
            rig.clock.t += 100
            rig.engine.tick()
    warnings = [r for r in caplog.records if "completion_seq" in r.getMessage()]
    assert len(warnings) == 1 and rig.lark.sent == []


def test_herdr_down_logs_only_on_transitions_and_recovers(rig: Rig, caplog: pytest.LogCaptureFixture):
    rig.pair()
    rig.herdr.down = True
    with caplog.at_level(logging.INFO):
        for _ in range(5):
            rig.engine.tick()
        down = [r for r in caplog.records if "herdr unavailable" in r.getMessage()]
        assert len(down) == 1
        rig.herdr.down = False
        rig.engine.tick()
        rig.engine.tick()
    assert len([r for r in caplog.records if "available again" in r.getMessage()]) == 1


def test_herdr_down_replies_to_owner_but_not_to_strangers_groups_or_redeliveries(rig: Rig):
    rig.pair()
    rig.herdr.down = True
    before = len(rig.lark.replies)
    rig.dm("/list", sender="ou_stranger")
    rig.dm("/list", chat="group")
    assert len(rig.lark.replies) == before
    rig.dm("/list", eid="dup")
    assert "herdr 不可用" in rig.last_reply() and len(rig.lark.replies) == before + 1
    rig.dm("/list", eid="dup")
    assert len(rig.lark.replies) == before + 1
    assert rig.engine.state.seen_events == ("dup",)


def test_failed_notification_send_backs_off_for_a_minute(rig: Rig):
    a = snap("t1", "blocked", pane="w1:p1", name="p", state_change_seq=3)
    rig.herdr.agents = [a]
    rig.pair()
    rig.engine.tick()
    rig.clock.t += 21
    rig.lark.fail_sends = True
    rig.engine.tick()
    assert rig.lark.send_attempts == 1
    rig.clock.t += NOTIFY_RETRY_SECONDS - 1
    rig.engine.tick()
    assert rig.lark.send_attempts == 1
    rig.clock.t += 2
    rig.engine.tick()
    assert rig.lark.send_attempts == 2
    rig.lark.fail_sends = False
    rig.clock.t += NOTIFY_RETRY_SECONDS + 1
    rig.engine.tick()
    assert len(rig.lark.sent) == 1


def test_no_owner_sends_nothing_and_unpair_stops_notifications(rig: Rig):
    rig.herdr.agents = [snap("t1", "blocked")]
    rig.engine.tick()
    rig.clock.t += 100
    rig.engine.tick()
    assert rig.lark.sent == []

    rig.pair()
    rig.clock.t += 100
    rig.engine.tick()
    assert len(rig.lark.sent) == 1
    rig.owner.delete()
    rig.herdr.agents = [snap("t2", "blocked", name="other")]
    rig.engine.tick()
    rig.clock.t += 100
    rig.engine.tick()
    assert len(rig.lark.sent) == 1


def test_group_message_with_correct_code_never_pairs(rig: Rig):
    code = rig.pairing.arm(rig.clock.t).code
    rig.dm(code, chat="group")
    assert rig.owner.read() is None and rig.pairing.load() is not None
    assert rig.lark.replies == []


def test_pairing_unarmed_does_nothing(rig: Rig):
    rig.dm("123456")
    assert rig.owner.read() is None and rig.lark.replies == []


def test_pairing_expired_code_is_refused_and_file_removed(rig: Rig):
    code = rig.pairing.arm(rig.clock.t).code
    rig.clock.t += 601
    rig.dm(code)
    assert rig.owner.read() is None and not rig.pairing.path.exists()


def test_pairing_five_wrong_codes_disarm_so_the_right_code_no_longer_pairs(rig: Rig):
    code = rig.pairing.arm(rig.clock.t).code
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(4):
        rig.dm(wrong)
        assert rig.pairing.path.exists()
    rig.dm(wrong)
    assert not rig.pairing.path.exists()
    rig.dm(code)
    assert rig.owner.read() is None


def test_pairing_success_writes_owner_and_removes_pairing_file(rig: Rig):
    rig.pair()
    assert not rig.pairing.path.exists()


def test_pairing_is_impossible_while_an_owner_file_exists(rig: Rig):
    rig.pair()
    code = rig.pairing.arm(rig.clock.t).code
    rig.dm(code, sender="ou_intruder")
    assert rig.owner.read() == OWNER

from pathlib import Path

from herdr_lark.daemon import Engine
from herdr_lark.models import Config, Inbound
from herdr_lark.store import StateStore

from helpers import FakeHerdr, FakeLark, snap, with_status

CFG = Config(blocked_delay_seconds=20, done_delay_seconds=60)
OWNER = "ou_owner"


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def build(tmp_path: Path):
    herdr, lark, clock = FakeHerdr(), FakeLark(), Clock()
    engine = Engine(herdr, lark, StateStore(tmp_path / "state.json"), CFG, clock)
    return engine, herdr, lark, clock


def pair(engine: Engine, lark: FakeLark) -> None:
    engine.tick()
    code = engine.state.pairing_code
    assert code and len(code) == 6
    engine.handle_inbound(Inbound("pair", "om_pair", OWNER, "p2p", code))
    assert engine.state.owner_open_id == OWNER
    assert "配对成功" in lark.replies[-1][1].text


def test_blocked_notification_reply_issues_herdr_keys(tmp_path: Path):
    engine, herdr, lark, clock = build(tmp_path)
    a = snap("t1", "idle", ws="w1", pane="w1:p1", name="planner")
    herdr.agents = [a]
    pair(engine, lark)

    herdr.agents = [with_status(a, "working", state_change_seq=2)]
    clock.t += 5
    engine.tick()
    herdr.agents = [with_status(a, "blocked", state_change_seq=3)]
    clock.t += 5
    engine.tick()
    assert lark.sent == []

    clock.t += 21
    herdr.screen = "Allow bash?\n1. Yes\n2. No\n\n"
    engine.tick()
    assert len(lark.sent) == 1
    to, out = lark.sent[0]
    assert to == OWNER
    assert "label-w1" in out.text and "planner" in out.text and "等待审批" in out.text
    assert out.code == "Allow bash?\n1. Yes\n2. No"
    clock.t += 30
    engine.tick()
    assert len(lark.sent) == 1

    notif_id = "om_sent_1"
    engine.handle_inbound(Inbound("r1", "om_r1", OWNER, "p2p", "1", parent_id=notif_id))
    assert herdr.calls == [("keys", "w1:p1", "1")]
    assert lark.replies[-1][0] == "om_r1"

    herdr.agents = [with_status(a, "working", state_change_seq=4)]
    engine.handle_inbound(Inbound("r2", "om_r2", OWNER, "p2p", "1", parent_id=notif_id))
    assert herdr.calls == [("keys", "w1:p1", "1")]
    assert "状态已变化" in lark.replies[-1][1].text


def test_done_notification_prompt_and_restart_has_no_duplicate(tmp_path: Path):
    engine, herdr, lark, clock = build(tmp_path)
    a = snap("t1", "working", pane="w1:p1", name="planner", completion_seq=1)
    herdr.agents = [a]
    pair(engine, lark)
    herdr.agents = [with_status(a, "done", completion_seq=2)]
    engine.tick()
    clock.t += 61
    engine.tick()
    assert len(lark.sent) == 1 and "已完成" in lark.sent[0][1].text

    engine2 = Engine(herdr, lark, StateStore(tmp_path / "state.json"), CFG, clock)
    clock.t += 600
    engine2.tick()
    assert len(lark.sent) == 1

    engine2.handle_inbound(Inbound("r1", "om_r1", OWNER, "p2p", "write tests", parent_id="om_sent_1"))
    assert herdr.calls == [("prompt", "w1:p1", "write tests")]


def test_herdr_down_does_not_raise_and_recovers(tmp_path: Path):
    engine, herdr, lark, clock = build(tmp_path)
    pair(engine, lark)
    herdr.down = True
    engine.tick()
    engine.handle_inbound(Inbound("r1", "om_r1", OWNER, "p2p", "/list"))
    assert "herdr 不可用" in lark.replies[-1][1].text
    herdr.down = False
    engine.tick()


def test_blocked_text_reply_sends_text_then_enter(tmp_path: Path):
    engine, herdr, lark, clock = build(tmp_path)
    a = snap("t1", "blocked", pane="w1:p1", name="p", state_change_seq=3)
    herdr.agents = [a]
    pair(engine, lark)
    engine.tick()
    clock.t += 21
    engine.tick()
    engine.handle_inbound(Inbound("r1", "om_r1", OWNER, "p2p", "use option B"))
    assert herdr.calls == [("text", "w1:p1", "use option B"), ("keys", "w1:p1", "enter")]


def test_no_owner_sends_nothing(tmp_path: Path):
    engine, herdr, lark, clock = build(tmp_path)
    herdr.agents = [snap("t1", "blocked")]
    engine.tick()
    clock.t += 100
    engine.tick()
    assert lark.sent == []

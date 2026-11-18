from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable, Sequence, assert_never

from .decide import decide
from .herdr import HerdrError, HerdrPort
from .lark import LarkClient, LarkError, LarkTransport
from .models import (
    Action,
    AgentSnapshot,
    Config,
    Ignore,
    Inbound,
    Keys,
    NOTIFY_RETRY_SECONDS,
    Notification,
    Outbound,
    Prompt,
    Read,
    Reply,
    State,
    Text,
    record_sent,
)
from .pairing import OwnerStore, PairingStore, attempt
from .render import READ_FACTOR, render_notification, screen_digest, tail_screen
from .route import admit, owner_action
from .store import StateStore

log = logging.getLogger(__name__)


class Engine:
    """Sole owner of State. Every method must be called from one thread."""

    def __init__(
        self,
        herdr: HerdrPort,
        lark: LarkTransport,
        store: StateStore,
        cfg: Config,
        owner: OwnerStore,
        pairing: PairingStore,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._herdr = herdr
        self._lark = lark
        self._store = store
        self._cfg = cfg
        self._owner = owner
        self._pairing = pairing
        self._clock = clock
        self.state: State = store.load()
        self._held_logged: set[tuple[str, str, int]] = set()
        self._retry_after: dict[tuple[str, str, int], float] = {}
        self._herdr_down = False
        self._warned_no_seq: set[str] = set()

    def _commit(self, new: State) -> None:
        if new != self.state:
            self.state = new
            self._store.save(new)

    def _note_herdr(self, error: HerdrError | None) -> None:
        if error is not None and not self._herdr_down:
            log.warning("herdr unavailable: %s", error)
        elif error is None and self._herdr_down:
            log.info("herdr available again")
        self._herdr_down = error is not None

    def _warn_missing_completion_seq(self, snapshots: Sequence[AgentSnapshot]) -> None:
        for s in snapshots:
            if s.status == "done" and s.completion_seq is None:
                if s.terminal_id not in self._warned_no_seq:
                    self._warned_no_seq.add(s.terminal_id)
                    log.warning("%s is done without completion_seq, skipping it", s.display_name)
            else:
                self._warned_no_seq.discard(s.terminal_id)

    def tick(self) -> None:
        try:
            snapshots = self._herdr.list_agents()
        except HerdrError as e:
            self._note_herdr(e)
            return
        self._note_herdr(None)
        self._warn_missing_completion_seq(snapshots)

        now = self._clock()
        new_state, due = decide(self.state, snapshots, now, self._cfg)
        self._commit(new_state)

        owner = self._owner.read()
        for n in due:
            key = (n.snapshot.terminal_id, n.kind, n.seq)
            if owner is None:
                if key not in self._held_logged:
                    self._held_logged.add(key)
                    log.info(
                        "not paired (run `herdr-lark pair`), holding %s notification for %s",
                        n.kind, n.snapshot.display_name,
                    )
                continue
            if now < self._retry_after.get(key, 0.0):
                continue
            if self._notify(n, owner):
                self._retry_after.pop(key, None)
            else:
                self._retry_after[key] = now + NOTIFY_RETRY_SECONDS

    def _notify(self, n: Notification, owner: str, note: str | None = None) -> bool:
        try:
            screen = self._herdr.read(n.snapshot.pane_id, self._screen_read_lines())
        except HerdrError as e:
            if n.kind == "blocked":
                log.warning("cannot read screen for %s: %s", n.snapshot.display_name, e)
                return False
            screen = f"(无法读取屏幕：{e})"
        digest = screen_digest(screen) if n.kind == "blocked" else None
        out = render_notification(n, screen, self._cfg.screen_lines, note)
        try:
            message_id = self._lark.send_to_user(owner, out)
        except LarkError as e:
            log.warning("notification send failed, retrying in %ds: %s", NOTIFY_RETRY_SECONDS, e)
            return False
        self._commit(record_sent(self.state, n, message_id, digest, self._clock()))
        log.info("notified %s for %s seq=%d", n.kind, n.snapshot.display_name, n.seq)
        return True

    def _screen_read_lines(self) -> int:
        return self._cfg.screen_lines * READ_FACTOR

    def handle_inbound(self, inbound: Inbound) -> None:
        now = self._clock()
        owner = self._owner.read()
        if owner is None:
            if inbound.chat_type == "p2p":
                self._pair(inbound, now)
            else:
                log.info("ignored inbound %s: not a p2p chat", inbound.message_id)
            return

        new_state, early = admit(inbound, owner, self.state, self._cfg, now)
        self._commit(new_state)
        if early is not None:
            self._execute(inbound, early, owner, [])
            return

        try:
            snapshots = self._herdr.list_agents()
        except HerdrError as e:
            self._note_herdr(e)
            self._reply(inbound, Reply(f"herdr 不可用：{e}"))
            return
        self._note_herdr(None)
        action = owner_action(inbound, self.state, snapshots, self._cfg, now)
        self._execute(inbound, action, owner, snapshots)

    def _pair(self, inbound: Inbound, now: float) -> None:
        remaining, outcome = attempt(self._pairing.load(), inbound.text, now)
        if outcome == "paired":
            self._owner.write(inbound.sender_open_id)
        if remaining is None:
            self._pairing.clear()
        else:
            self._pairing.save(remaining)
        log.info("pairing attempt from %s: %s", inbound.sender_open_id, outcome)
        if outcome == "paired":
            self._reply(
                inbound, Reply("配对成功。之后 agent 的审批和完成通知会发到这里。发 /help 查看用法。")
            )

    def _dialog_unchanged(self, pane_id: str, expected: str) -> bool:
        return screen_digest(self._herdr.read(pane_id, self._screen_read_lines())) == expected

    def _dialog_changed(
        self, inbound: Inbound, owner: str, pane_id: str, snapshots: Sequence[AgentSnapshot]
    ) -> None:
        s = next((x for x in snapshots if x.pane_id == pane_id), None)
        sent = s is not None and self._notify(
            Notification(s, "blocked", s.state_change_seq),
            owner,
            "对话框已变化，你刚才的回复没有执行。请看下面的最新屏幕，并引用回复这条新消息。",
        )
        self._reply(
            inbound,
            Reply("对话框已变化，未执行任何操作。" + ("已发送最新屏幕。" if sent else "发 /read 查看当前屏幕。")),
        )

    def _execute(
        self, inbound: Inbound, action: Action, owner: str, snapshots: Sequence[AgentSnapshot]
    ) -> None:
        try:
            match action:
                case Ignore(reason):
                    log.info("ignored inbound %s: %s", inbound.message_id, reason)
                case Reply():
                    self._reply(inbound, action)
                case Prompt(pane_id, text):
                    self._herdr.prompt(pane_id, text)
                    self._reply(inbound, Reply("已发送。"))
                case Keys(pane_id, keys, digest):
                    if not self._dialog_unchanged(pane_id, digest):
                        self._dialog_changed(inbound, owner, pane_id, snapshots)
                        return
                    self._herdr.send_keys(pane_id, keys)
                    self._reply(inbound, Reply(f"已发送按键：{' '.join(keys)}"))
                case Text(pane_id, text, digest):
                    if not self._dialog_unchanged(pane_id, digest):
                        self._dialog_changed(inbound, owner, pane_id, snapshots)
                        return
                    self._herdr.send_text(pane_id, text)
                    self._herdr.send_keys(pane_id, ("enter",))
                    self._reply(inbound, Reply("已输入并回车。"))
                case Read(pane_id, lines):
                    screen = tail_screen(self._herdr.read(pane_id, lines * READ_FACTOR), lines)
                    self._reply(inbound, Reply("屏幕内容：", screen or "(屏幕为空)"))
                case _:
                    assert_never(action)
        except HerdrError as e:
            log.warning("herdr command failed: %s", e)
            self._reply(inbound, Reply(f"herdr 执行失败：{e}"))

    def _reply(self, inbound: Inbound, r: Reply) -> None:
        try:
            self._lark.reply(inbound.message_id, Outbound(None, r.text, r.code))
        except LarkError as e:
            log.warning("reply failed: %s", e)


class _Tick:
    pass


def run_daemon(engine: Engine, lark: LarkClient, poll_seconds: float) -> None:
    inbox: queue.Queue[_Tick | Inbound] = queue.Queue()

    def ticker() -> None:
        while True:
            if inbox.empty():
                inbox.put(_Tick())
            time.sleep(poll_seconds)

    def worker() -> None:
        while True:
            item = inbox.get()
            try:
                if isinstance(item, _Tick):
                    engine.tick()
                else:
                    engine.handle_inbound(item)
            except Exception:
                log.exception("engine step failed")

    threading.Thread(target=worker, name="engine", daemon=True).start()
    threading.Thread(target=ticker, name="ticker", daemon=True).start()
    lark.listen(inbox.put)

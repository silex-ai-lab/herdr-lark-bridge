from __future__ import annotations

import logging
import queue
import secrets
import threading
import time
from dataclasses import replace
from typing import Callable, assert_never

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
    Outbound,
    Prompt,
    Read,
    Reply,
    State,
    Text,
    record_sent,
)
from .render import READ_FACTOR, render_notification, tail_screen
from .route import route
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
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._herdr = herdr
        self._lark = lark
        self._store = store
        self._cfg = cfg
        self._clock = clock
        self.state: State = store.load()
        self._held_logged: set[tuple[str, str, int]] = set()

    def _commit(self, new: State) -> None:
        if new != self.state:
            self.state = new
            self._store.save(new)

    def tick(self) -> None:
        if self.state.owner_open_id is None and self.state.pairing_code is None:
            code = f"{secrets.randbelow(10**6):06d}"
            self._commit(replace(self.state, pairing_code=code))
            log.info("pairing code generated; run `herdr-lark pair-code`")

        try:
            snapshots = self._herdr.list_agents()
        except HerdrError as e:
            log.warning("herdr unavailable, retrying next tick: %s", e)
            return

        new_state, due = decide(self.state, snapshots, self._clock(), self._cfg)
        self._commit(new_state)

        owner = self.state.owner_open_id
        for n in due:
            if owner is None:
                key = (n.snapshot.terminal_id, n.kind, n.seq)
                if key not in self._held_logged:
                    self._held_logged.add(key)
                    log.info("no owner paired, holding %s notification for %s", n.kind, n.snapshot.display_name)
                continue
            try:
                screen = self._herdr.read(n.snapshot.pane_id, self._cfg.screen_lines * READ_FACTOR)
            except HerdrError as e:
                screen = f"(无法读取屏幕：{e})"
            out = render_notification(n, screen, self._cfg.screen_lines)
            try:
                message_id = self._lark.send_to_user(owner, out)
            except LarkError as e:
                log.warning("notification send failed, retrying next tick: %s", e)
                continue
            self._commit(record_sent(self.state, n, message_id))
            log.info("notified %s for %s seq=%d", n.kind, n.snapshot.display_name, n.seq)

    def handle_inbound(self, inbound: Inbound) -> None:
        snapshots: list[AgentSnapshot] = []
        try:
            snapshots = self._herdr.list_agents()
        except HerdrError as e:
            if inbound.sender_open_id == self.state.owner_open_id:
                self._reply(inbound, Reply(f"herdr 不可用：{e}"))
                return
            log.warning("herdr unavailable while routing: %s", e)

        new_state, action = route(inbound, self.state, snapshots, self._cfg)
        self._commit(new_state)
        self._execute(inbound, action)

    def _execute(self, inbound: Inbound, action: Action) -> None:
        try:
            match action:
                case Ignore(reason):
                    log.info("ignored inbound %s: %s", inbound.message_id, reason)
                case Reply():
                    self._reply(inbound, action)
                case Prompt(pane_id, text):
                    self._herdr.prompt(pane_id, text)
                    self._reply(inbound, Reply("已发送。"))
                case Keys(pane_id, keys):
                    self._herdr.send_keys(pane_id, keys)
                    self._reply(inbound, Reply(f"已发送按键：{' '.join(keys)}"))
                case Text(pane_id, text, then_enter):
                    self._herdr.send_text(pane_id, text)
                    if then_enter:
                        self._herdr.send_keys(pane_id, ("enter",))
                    self._reply(inbound, Reply("已输入并回车。" if then_enter else "已输入。"))
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

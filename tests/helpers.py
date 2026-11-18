from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from herdr_lark.herdr import HerdrError
from herdr_lark.lark import LarkError
from herdr_lark.models import AgentSnapshot, AgentStatus, Outbound


def snap(
    tid: str = "t1",
    status: AgentStatus = "idle",
    ws: str = "w1",
    pane: str | None = None,
    name: str | None = "alpha",
    completion_seq: int | None = 1,
    state_change_seq: int = 1,
) -> AgentSnapshot:
    return AgentSnapshot(
        terminal_id=tid,
        pane_id=pane or f"{ws}:{tid}",
        workspace_id=ws,
        workspace_label=f"label-{ws}",
        agent="claude",
        status=status,
        completion_seq=completion_seq,
        state_change_seq=state_change_seq,
        name=name,
        cwd="/x",
    )


def with_status(s: AgentSnapshot, status: AgentStatus, **kw: int | None) -> AgentSnapshot:
    return replace(s, status=status, **kw)


class FakeHerdr:
    def __init__(self, agents: Sequence[AgentSnapshot] = ()) -> None:
        self.agents = list(agents)
        self.down = False
        self.screen = "line1\nline2\n\n"
        self.calls: list[tuple[str, ...]] = []

    def list_agents(self) -> list[AgentSnapshot]:
        if self.down:
            raise HerdrError("herdr not running")
        return list(self.agents)

    def read(self, pane_id: str, lines: int) -> str:
        return self.screen

    def read_visible(self, pane_id: str) -> str:
        return self.screen

    def prompt(self, pane_id: str, text: str) -> None:
        self.calls.append(("prompt", pane_id, text))

    def send_keys(self, pane_id: str, keys: Sequence[str]) -> None:
        self.calls.append(("keys", pane_id, *keys))

    def send_text(self, pane_id: str, text: str) -> None:
        self.calls.append(("text", pane_id, text))


class FakeLark:
    def __init__(self) -> None:
        self.sent: list[tuple[str, Outbound]] = []
        self.replies: list[tuple[str, Outbound]] = []
        self.fail_sends = False
        self.send_attempts = 0

    def send_to_user(self, open_id: str, out: Outbound) -> str:
        self.send_attempts += 1
        if self.fail_sends:
            raise LarkError("boom")
        self.sent.append((open_id, out))
        return f"om_sent_{len(self.sent)}"

    def reply(self, message_id: str, out: Outbound) -> str:
        self.replies.append((message_id, out))
        return f"om_reply_{len(self.replies)}"


class FakeLarkApi(FakeLark):
    def __init__(self, error: str | None = None) -> None:
        super().__init__()
        self.error = error
        self.checks = 0

    def check_credentials(self) -> None:
        self.checks += 1
        if self.error:
            raise LarkError(self.error)


class FakeLaunchctl:
    def __init__(self, print_output: str = "", print_code: int = 0) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.print_output = print_output
        self.print_code = print_code
        self.bootstrap_code = 0

    def __call__(self, args: Sequence[str]) -> tuple[int, str]:
        self.calls.append(tuple(args))
        if args[0] == "print":
            return self.print_code, self.print_output
        if args[0] == "bootstrap":
            return self.bootstrap_code, "" if self.bootstrap_code == 0 else "boom"
        return 0, ""

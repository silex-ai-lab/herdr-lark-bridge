from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal, Mapping

AgentStatus = Literal["idle", "working", "blocked", "done", "unknown"]
AttentionKind = Literal["blocked", "done"]

STATUSES: tuple[AgentStatus, ...] = ("idle", "working", "blocked", "done", "unknown")

MESSAGE_MAP_CAP = 200
SEEN_EVENTS_CAP = 500
NOTIFY_RETRY_SECONDS = 60.0


@dataclass(frozen=True)
class Config:
    poll_seconds: float = 3.0
    blocked_delay_seconds: float = 20.0
    done_delay_seconds: float = 60.0
    screen_lines: int = 40
    read_lines: int = 40
    shortcut_minutes: float = 30.0
    max_inbound_age_seconds: float = 120.0
    prune_after_seconds: float = 600.0


@dataclass(frozen=True)
class AgentSnapshot:
    terminal_id: str
    pane_id: str
    workspace_id: str
    workspace_label: str
    agent: str
    status: AgentStatus
    completion_seq: int | None
    state_change_seq: int
    name: str | None
    cwd: str

    @property
    def display_name(self) -> str:
        return self.name or f"{self.agent} {self.pane_id}"

    def seq_for(self, kind: AttentionKind) -> int | None:
        return self.state_change_seq if kind == "blocked" else self.completion_seq


@dataclass(frozen=True)
class Attention:
    kind: AttentionKind
    terminal_id: str
    seq: int
    first_seen: float


@dataclass(frozen=True)
class MessageRef:
    terminal_id: str
    kind: AttentionKind
    seq: int
    digest: str | None = None
    sent_at: float = 0.0


@dataclass(frozen=True)
class Notification:
    snapshot: AgentSnapshot
    kind: AttentionKind
    seq: int


@dataclass(frozen=True)
class State:
    pending: Mapping[tuple[str, AttentionKind], Attention] = field(
        default_factory=dict[tuple[str, AttentionKind], Attention]
    )
    notified: Mapping[str, Mapping[AttentionKind, int]] = field(
        default_factory=dict[str, Mapping[AttentionKind, int]]
    )
    messages: Mapping[str, MessageRef] = field(default_factory=dict[str, MessageRef])
    last_seen: Mapping[str, float] = field(default_factory=dict[str, float])
    seen_events: tuple[str, ...] = ()


@dataclass(frozen=True)
class Inbound:
    event_id: str
    message_id: str
    sender_open_id: str
    chat_type: str
    text: str
    parent_id: str | None = None
    root_id: str | None = None
    created_at: float | None = None


@dataclass(frozen=True)
class Outbound:
    title: str | None
    text: str
    code: str | None = None
    footer: str | None = None


@dataclass(frozen=True)
class Prompt:
    pane_id: str
    text: str


@dataclass(frozen=True)
class Keys:
    pane_id: str
    keys: tuple[str, ...]
    expect_digest: str


@dataclass(frozen=True)
class Text:
    pane_id: str
    text: str
    expect_digest: str


@dataclass(frozen=True)
class Read:
    pane_id: str
    lines: int


@dataclass(frozen=True)
class Reply:
    text: str
    code: str | None = None


@dataclass(frozen=True)
class Ignore:
    reason: str


Action = Prompt | Keys | Text | Read | Reply | Ignore


def record_sent(
    state: State, n: Notification, message_id: str, digest: str | None, now: float
) -> State:
    notified: dict[str, dict[AttentionKind, int]] = {
        t: dict(k) for t, k in state.notified.items()
    }
    notified.setdefault(n.snapshot.terminal_id, {})[n.kind] = n.seq
    messages: dict[str, MessageRef] = dict(state.messages)
    messages[message_id] = MessageRef(n.snapshot.terminal_id, n.kind, n.seq, digest, now)
    while len(messages) > MESSAGE_MAP_CAP:
        del messages[next(iter(messages))]
    return replace(state, notified=notified, messages=messages)

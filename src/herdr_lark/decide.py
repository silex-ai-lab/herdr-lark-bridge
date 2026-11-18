from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from .models import (
    AgentSnapshot,
    Attention,
    AttentionKind,
    Config,
    Notification,
    State,
)


def decide(
    state: State, snapshots: Sequence[AgentSnapshot], now: float, cfg: Config
) -> tuple[State, list[Notification]]:
    live = {s.terminal_id: s for s in snapshots}

    pending: dict[tuple[str, AttentionKind], Attention] = {}
    for s in snapshots:
        kind: AttentionKind | None = (
            "blocked" if s.status == "blocked" else "done" if s.status == "done" else None
        )
        if kind is None:
            continue
        seq = s.seq_for(kind)
        old = state.pending.get((s.terminal_id, kind))
        first_seen = old.first_seen if old is not None and old.seq == seq else now
        pending[(s.terminal_id, kind)] = Attention(kind, s.terminal_id, seq, first_seen)

    notified = {
        tid: dict(kinds) for tid, kinds in state.notified.items() if tid in live
    }
    if not state.baselined:
        for s in snapshots:
            if s.status == "done":
                notified.setdefault(s.terminal_id, {})["done"] = s.completion_seq

    messages = {m: r for m, r in state.messages.items() if r.terminal_id in live}

    working_workspaces = {s.workspace_id for s in snapshots if s.status == "working"}

    due: list[Notification] = []
    for (tid, kind), att in pending.items():
        s = live[tid]
        if notified.get(tid, {}).get(kind) == att.seq:
            continue
        delay = cfg.blocked_delay_seconds if kind == "blocked" else cfg.done_delay_seconds
        if now - att.first_seen < delay:
            continue
        if kind == "done" and s.workspace_id in working_workspaces:
            continue
        due.append(Notification(s, kind, att.seq))

    new_state = replace(
        state,
        baselined=True,
        pending=pending,
        notified=notified,
        messages=messages,
    )
    return new_state, due

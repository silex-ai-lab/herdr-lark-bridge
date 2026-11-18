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
        if seq is None:
            continue
        old = state.pending.get((s.terminal_id, kind))
        first_seen = old.first_seen if old is not None and old.seq == seq else now
        pending[(s.terminal_id, kind)] = Attention(kind, s.terminal_id, seq, first_seen)

    notified = {tid: dict(kinds) for tid, kinds in state.notified.items()}
    last_seen = dict(state.last_seen)
    for tid in {*notified, *(r.terminal_id for r in state.messages.values())}:
        last_seen.setdefault(tid, now)
    for s in snapshots:
        if s.terminal_id not in last_seen and s.status == "done" and s.completion_seq is not None:
            notified.setdefault(s.terminal_id, {}).setdefault("done", s.completion_seq)
        last_seen[s.terminal_id] = now

    expired = {
        tid for tid, seen in last_seen.items()
        if tid not in live and now - seen > cfg.prune_after_seconds
    }
    for tid in expired:
        del last_seen[tid]
        notified.pop(tid, None)
    messages = {m: r for m, r in state.messages.items() if r.terminal_id not in expired}

    working_workspaces = {s.workspace_id for s in snapshots if s.status == "working"}

    due: list[Notification] = []
    for (tid, kind), att in pending.items():
        s = live[tid]
        last = notified.get(tid, {}).get(kind)
        if last is not None and (att.seq <= last if kind == "done" else att.seq == last):
            continue
        delay = cfg.blocked_delay_seconds if kind == "blocked" else cfg.done_delay_seconds
        if now - att.first_seen < delay:
            continue
        if kind == "done" and s.workspace_id in working_workspaces:
            continue
        due.append(Notification(s, kind, att.seq))

    new_state = replace(
        state, pending=pending, notified=notified, messages=messages, last_seen=last_seen
    )
    return new_state, due

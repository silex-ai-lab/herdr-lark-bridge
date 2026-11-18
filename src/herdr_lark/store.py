from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, cast

from .fsio import atomic_write
from .models import Attention, AttentionKind, MessageRef, State

log = logging.getLogger(__name__)


def state_to_json(s: State) -> dict[str, Any]:
    return {
        "pending": [
            {"kind": a.kind, "terminal_id": a.terminal_id, "seq": a.seq, "first_seen": a.first_seen}
            for a in s.pending.values()
        ],
        "notified": {t: dict(k) for t, k in s.notified.items()},
        "messages": {
            m: {
                "terminal_id": r.terminal_id,
                "kind": r.kind,
                "seq": r.seq,
                "digest": r.digest,
                "sent_at": r.sent_at,
            }
            for m, r in s.messages.items()
        },
        "last_seen": dict(s.last_seen),
        "seen_events": list(s.seen_events),
    }


def state_from_json(d: dict[str, Any]) -> State:
    pending: dict[tuple[str, AttentionKind], Attention] = {
        (str(p["terminal_id"]), cast(AttentionKind, p["kind"])): Attention(
            cast(AttentionKind, p["kind"]), p["terminal_id"], int(p["seq"]), float(p["first_seen"])
        )
        for p in d.get("pending", [])
    }
    return State(
        pending=pending,
        notified={
            t: {cast(AttentionKind, k): int(v) for k, v in kinds.items()}
            for t, kinds in d.get("notified", {}).items()
        },
        messages={
            m: MessageRef(
                r["terminal_id"],
                cast(AttentionKind, r["kind"]),
                int(r["seq"]),
                r.get("digest"),
                float(r.get("sent_at", 0.0)),
            )
            for m, r in d.get("messages", {}).items()
        },
        last_seen={t: float(v) for t, v in d.get("last_seen", {}).items()},
        seen_events=tuple(d.get("seen_events", ())),
    )


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> State:
        try:
            raw = self.path.read_text()
        except FileNotFoundError:
            return State()
        try:
            return state_from_json(json.loads(raw))
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            aside = self.path.with_name(f"{self.path.name}.corrupt-{int(time.time())}")
            os.replace(self.path, aside)
            log.error("state file unreadable (%s), moved to %s, starting fresh", e, aside)
            return State()

    def save(self, state: State) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write(self.path, json.dumps(state_to_json(state), ensure_ascii=False, indent=1))

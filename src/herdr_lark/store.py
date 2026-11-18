from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

from .models import Attention, AttentionKind, MessageRef, State


def state_to_json(s: State) -> dict[str, Any]:
    return {
        "owner_open_id": s.owner_open_id,
        "pairing_code": s.pairing_code,
        "pair_failures": s.pair_failures,
        "baselined": s.baselined,
        "pending": [
            {"kind": a.kind, "terminal_id": a.terminal_id, "seq": a.seq, "first_seen": a.first_seen}
            for a in s.pending.values()
        ],
        "notified": {t: dict(k) for t, k in s.notified.items()},
        "messages": {
            m: {"terminal_id": r.terminal_id, "kind": r.kind, "seq": r.seq}
            for m, r in s.messages.items()
        },
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
        owner_open_id=d.get("owner_open_id"),
        pairing_code=d.get("pairing_code"),
        pair_failures=int(d.get("pair_failures", 0)),
        baselined=bool(d.get("baselined", False)),
        pending=pending,
        notified={
            t: {cast(AttentionKind, k): int(v) for k, v in kinds.items()}
            for t, kinds in d.get("notified", {}).items()
        },
        messages={
            m: MessageRef(r["terminal_id"], cast(AttentionKind, r["kind"]), int(r["seq"]))
            for m, r in d.get("messages", {}).items()
        },
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
        return state_from_json(json.loads(raw))

    def save(self, state: State) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state_to_json(state), ensure_ascii=False, indent=1))
        os.replace(tmp, self.path)

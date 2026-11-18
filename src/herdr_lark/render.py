from __future__ import annotations

import hashlib

from .messages import Messages
from .models import Notification, Outbound

MAX_CODE_CHARS = 8_000
DIGEST_LINES = 15

RULE_CHARS = frozenset("─━═-_╌┄")
RULE_WIDTH = 24
READ_FACTOR = 5


def _compact(raw: str) -> list[str]:
    rows: list[str] = []
    for r in (x.rstrip() for x in raw.splitlines()):
        body = r.strip()
        if len(body) > RULE_WIDTH and set(body) <= RULE_CHARS:
            r = body[:RULE_WIDTH]
        if not r and (not rows or not rows[-1]):
            continue
        rows.append(r)
    while rows and not rows[-1]:
        rows.pop()
    return rows


def tail_screen(raw: str, lines: int, m: Messages) -> str:
    text = "\n".join(_compact(raw)[-lines:])
    if len(text) > MAX_CODE_CHARS:
        text = m.truncated + "\n" + text[-MAX_CODE_CHARS:]
    return text


def screen_digest(raw: str) -> str:
    tail = "\n".join(_compact(raw)[-DIGEST_LINES:])
    return hashlib.sha256(tail.encode()).hexdigest()


def render_notification(
    n: Notification, screen: str, lines: int, m: Messages, note: str | None = None
) -> Outbound:
    s = n.snapshot
    needs = m.needs_blocked if n.kind == "blocked" else m.needs_done
    hint = m.hint_blocked if n.kind == "blocked" else m.hint_done
    header = f"[{s.workspace_label}] {s.display_name} ({s.agent})\n{needs}"
    if note:
        header = f"{note}\n{header}"
    return Outbound(
        title=f"{s.display_name}: {needs}",
        text=header,
        code=tail_screen(screen, lines, m) or m.screen_empty,
        footer=hint,
    )

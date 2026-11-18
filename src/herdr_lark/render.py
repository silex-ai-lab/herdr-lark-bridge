from __future__ import annotations

import hashlib

from .models import Notification, Outbound

MAX_CODE_CHARS = 8_000
DIGEST_LINES = 15

NEEDS = {"blocked": "等待审批", "done": "已完成，等你下一步"}

HINTS = {
    "blocked": (
        "引用回复本消息。按键：只写按键名，如 1、y、down enter（y n 0-9 enter esc tab up down left right space）。"
        "输入文字：以「输入 」或「text 」开头，其后内容原样输入并回车。其他回复（如 yes、no、是、否）不会被执行。"
    ),
    "done": "引用回复本消息，内容会作为新提示词发送。",
}


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


def tail_screen(raw: str, lines: int) -> str:
    text = "\n".join(_compact(raw)[-lines:])
    if len(text) > MAX_CODE_CHARS:
        text = "…(已截断)\n" + text[-MAX_CODE_CHARS:]
    return text


def screen_digest(raw: str) -> str:
    tail = "\n".join(_compact(raw)[-DIGEST_LINES:])
    return hashlib.sha256(tail.encode()).hexdigest()


def render_notification(
    n: Notification, screen: str, lines: int, note: str | None = None
) -> Outbound:
    s = n.snapshot
    header = (
        f"[{s.workspace_label}] {s.display_name} ({s.agent})\n"
        f"{NEEDS[n.kind]}"
    )
    if note:
        header = f"{note}\n{header}"
    return Outbound(
        title=f"{s.display_name}：{NEEDS[n.kind]}",
        text=header,
        code=tail_screen(screen, lines) or "(屏幕为空)",
        footer=HINTS[n.kind],
    )

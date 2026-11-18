from __future__ import annotations

from .models import Notification, Outbound

MAX_CODE_CHARS = 20_000

NEEDS = {"blocked": "等待审批", "done": "已完成，等你下一步"}

HINTS = {
    "blocked": "引用回复本消息：y / n / 1 / 2 / enter / esc 等按键，或任意文字（原样输入后回车）。",
    "done": "引用回复本消息，内容会作为新提示词发送。",
}


def tail_screen(raw: str, lines: int) -> str:
    rows = [r.rstrip() for r in raw.splitlines()]
    while rows and not rows[-1]:
        rows.pop()
    text = "\n".join(rows[-lines:])
    if len(text) > MAX_CODE_CHARS:
        text = "…(已截断)\n" + text[-MAX_CODE_CHARS:]
    return text


def render_notification(n: Notification, screen: str, lines: int) -> Outbound:
    s = n.snapshot
    header = (
        f"[{s.workspace_label}] {s.display_name} ({s.agent})\n"
        f"{NEEDS[n.kind]}"
    )
    return Outbound(
        title=f"{s.display_name}：{NEEDS[n.kind]}",
        text=header,
        code=tail_screen(screen, lines) or "(屏幕为空)",
        footer=HINTS[n.kind],
    )

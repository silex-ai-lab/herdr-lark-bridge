from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Sequence

from .models import (
    SEEN_EVENTS_CAP,
    Action,
    AgentSnapshot,
    Config,
    Ignore,
    Inbound,
    Keys,
    MessageRef,
    Prompt,
    Read,
    Reply,
    State,
    Text,
)

KEY_TOKENS = frozenset(
    {"y", "n", "enter", "esc", "tab", "up", "down", "left", "right", "space"}
    | set("0123456789")
)

TEXT_PREFIXES = ("输入 ", "text ")

STATUS_ZH = {
    "idle": "空闲",
    "working": "工作中",
    "blocked": "等待审批",
    "done": "已完成",
    "unknown": "未知",
}

BLOCKED_USAGE = (
    "等待审批的 agent 只接受两种回复，其他内容（包括 yes、no、是、否）不会被执行：\n"
    "1. 按键：只写按键名，空格分隔，可多个，例如 1 或 down down enter。"
    "可用 y n 0-9 enter esc tab up down left right space。\n"
    "2. 输入文字：以「输入 」或「text 」开头，其后的内容原样输入并回车。\n"
    "未执行任何操作。"
)

HELP = (
    "用法\n"
    "回复(引用)某条通知，内容会送进对应的 agent。\n"
    "等待审批：只含按键名（y n 0-9 enter esc tab up down left right space）时按键发送；"
    "「输入 文字」或「text 文字」会原样输入后回车；其他内容不会执行。\n"
    "已完成：内容作为新提示词发送。\n"
    "不引用直接发文字：仅当只有一条待处理通知且发出不超过 {minutes:g} 分钟时生效。\n"
    "命令：/list，/read <编号或名称>，/to <编号或名称> <文字>，/help"
)

LATE = "这条消息到达过晚（或缺少发送时间），为安全起见未执行。请重新发送。"
NO_DIGEST = "这条通知没有记录当时的屏幕内容，无法确认对话框是否一致，未执行。请等待新的通知。"


def help_text(cfg: Config) -> str:
    return HELP.format(minutes=cfg.shortcut_minutes)


def ordered(snapshots: Sequence[AgentSnapshot]) -> list[AgentSnapshot]:
    return sorted(snapshots, key=lambda s: (s.workspace_label, s.pane_id))


def admit(
    inbound: Inbound, owner: str, state: State, cfg: Config, now: float
) -> tuple[State, Action | None]:
    if inbound.chat_type != "p2p":
        return state, Ignore("not a p2p chat")
    if inbound.sender_open_id != owner:
        return state, Ignore(f"sender {inbound.sender_open_id} is not the owner")
    if inbound.event_id in state.seen_events:
        return state, Ignore("redelivered event")
    state = replace(
        state,
        seen_events=(*state.seen_events, inbound.event_id)[-SEEN_EVENTS_CAP:],
    )
    if inbound.created_at is None or now - inbound.created_at > cfg.max_inbound_age_seconds:
        return state, Reply(LATE)
    return state, None


def owner_action(
    inbound: Inbound,
    state: State,
    snapshots: Sequence[AgentSnapshot],
    cfg: Config,
    now: float,
) -> Action:
    text = inbound.text.strip()
    if not text:
        return Reply("只支持文本消息。\n" + help_text(cfg))

    live = {s.terminal_id: s for s in snapshots}
    is_reply = inbound.parent_id is not None or inbound.root_id is not None

    if is_reply:
        ref = next(
            (
                state.messages[m]
                for m in (inbound.parent_id, inbound.root_id)
                if m is not None and m in state.messages
            ),
            None,
        )
        if ref is None:
            return Reply("找不到这条消息对应的通知，可能已过期。发 /list 查看当前 agent。")
        if ref.kind == "blocked" and text.startswith("/"):
            return _command(text, snapshots, cfg)
        if _predates(inbound, ref):
            return Reply(LATE)
        return _act_on_ref(ref, text, live)

    if text.startswith("/"):
        return _command(text, snapshots, cfg)

    outstanding = _outstanding(state, live)
    if len(outstanding) != 1:
        return Reply(_outstanding_listing(outstanding, live) + "\n\n" + help_text(cfg))
    ref = outstanding[0]
    if now - ref.sent_at > cfg.shortcut_minutes * 60:
        return Reply(
            f"最近一条通知已超过 {cfg.shortcut_minutes:g} 分钟，不再接受不引用的回复。"
            "请引用回复通知，或发 /list。"
        )
    if _predates(inbound, ref):
        return Reply(LATE)
    return _act_on_ref(ref, text, live)


def _predates(inbound: Inbound, ref: MessageRef) -> bool:
    return inbound.created_at is None or inbound.created_at < ref.sent_at


def _guard(ref: MessageRef, live: Mapping[str, AgentSnapshot]) -> AgentSnapshot | str:
    s = live.get(ref.terminal_id)
    if s is None:
        return "该 agent 已不存在。"
    if ref.kind == "blocked":
        ok = s.status == "blocked" and s.state_change_seq == ref.seq
    else:
        ok = s.status in ("idle", "done") and s.completion_seq == ref.seq
    if not ok:
        return f"状态已变化，{s.display_name} 当前状态：{STATUS_ZH[s.status]}。未执行任何操作。"
    return s


def _act_on_ref(ref: MessageRef, text: str, live: Mapping[str, AgentSnapshot]) -> Action:
    s = _guard(ref, live)
    if isinstance(s, str):
        return Reply(s)
    if ref.kind == "done":
        return Prompt(s.pane_id, text)
    if ref.digest is None:
        return Reply(NO_DIGEST)
    tokens = text.lower().split()
    if tokens and all(t in KEY_TOKENS for t in tokens):
        return Keys(s.pane_id, tuple(tokens), ref.digest)
    for prefix in TEXT_PREFIXES:
        if text.lower().startswith(prefix):
            return Text(s.pane_id, text[len(prefix):], ref.digest)
    return Reply(BLOCKED_USAGE)


def _outstanding(state: State, live: Mapping[str, AgentSnapshot]) -> list[MessageRef]:
    latest: dict[str, MessageRef] = {}
    for ref in state.messages.values():
        latest[ref.terminal_id] = ref
    return [r for r in latest.values() if not isinstance(_guard(r, live), str)]


def _outstanding_listing(refs: Sequence[MessageRef], live: Mapping[str, AgentSnapshot]) -> str:
    if not refs:
        return "当前没有待处理的通知。"
    lines = ["有多条待处理通知，请引用回复其中一条："]
    for r in refs:
        s = live[r.terminal_id]
        lines.append(f"- {s.workspace_label} / {s.display_name}：{STATUS_ZH[s.status]}")
    return "\n".join(lines)


def _command(text: str, snapshots: Sequence[AgentSnapshot], cfg: Config) -> Action:
    parts = text.split(maxsplit=2)
    cmd = parts[0].lower()
    agents = ordered(snapshots)

    if cmd == "/help":
        return Reply(help_text(cfg))
    if cmd == "/list":
        if not agents:
            return Reply("当前没有 agent。")
        return Reply(
            "\n".join(
                f"{i}. {s.workspace_label} / {s.display_name} [{s.agent}] {STATUS_ZH[s.status]}"
                for i, s in enumerate(agents, 1)
            )
        )
    if cmd == "/read":
        if len(parts) < 2:
            return Reply("用法：/read <编号或名称>")
        found = _select(parts[1], agents)
        if isinstance(found, str):
            return Reply(found)
        return Read(found.pane_id, cfg.read_lines)
    if cmd == "/to":
        if len(parts) < 3:
            return Reply("用法：/to <编号或名称> <文字>")
        found = _select(parts[1], agents)
        if isinstance(found, str):
            return Reply(found)
        if found.status not in ("idle", "done"):
            return Reply(
                f"{found.display_name} 当前状态：{STATUS_ZH[found.status]}，只能给空闲或已完成的 agent 发送。"
            )
        return Prompt(found.pane_id, parts[2])
    return Reply(f"未知命令 {cmd}。\n" + help_text(cfg))


def _select(sel: str, agents: Sequence[AgentSnapshot]) -> AgentSnapshot | str:
    if sel.isdigit():
        i = int(sel)
        if 1 <= i <= len(agents):
            return agents[i - 1]
        return f"编号 {sel} 超出范围，发 /list 查看。"
    key = sel.lower()
    hits = [s for s in agents if key in (s.display_name.lower(), s.pane_id.lower())]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        return f"找不到 {sel}，发 /list 查看。"
    return f"{sel} 匹配多个 agent，请用编号。"

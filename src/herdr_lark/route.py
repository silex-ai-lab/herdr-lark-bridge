from __future__ import annotations

import hmac
from dataclasses import replace
from typing import Mapping, Sequence

from .models import (
    MAX_PAIR_FAILURES,
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

STATUS_ZH = {
    "idle": "空闲",
    "working": "工作中",
    "blocked": "等待审批",
    "done": "已完成",
    "unknown": "未知",
}

HELP = (
    "用法\n"
    "回复(引用)某条通知，内容会送进对应的 agent。\n"
    "等待审批：只包含 y n 1 2 3 enter esc tab up down left right space 的内容会按键发送，其他文字原样输入后回车。\n"
    "已完成：内容作为新提示词发送。\n"
    "命令：/list，/read <编号或名称>，/to <编号或名称> <文字>，/help"
)


def ordered(snapshots: Sequence[AgentSnapshot]) -> list[AgentSnapshot]:
    return sorted(snapshots, key=lambda s: (s.workspace_label, s.pane_id))


def route(
    inbound: Inbound,
    state: State,
    snapshots: Sequence[AgentSnapshot],
    cfg: Config = Config(),
) -> tuple[State, Action]:
    if inbound.event_id in state.seen_events:
        return state, Ignore("redelivered event")
    state = replace(
        state,
        seen_events=(*state.seen_events, inbound.event_id)[-SEEN_EVENTS_CAP:],
    )

    if inbound.chat_type != "p2p":
        return state, Ignore("not a p2p chat")

    if state.owner_open_id is None:
        return _pair(inbound, state)
    if inbound.sender_open_id != state.owner_open_id:
        return state, Ignore(f"sender {inbound.sender_open_id} is not the owner")

    return state, _owner_action(inbound, state, snapshots, cfg)


def _pair(inbound: Inbound, state: State) -> tuple[State, Action]:
    code = state.pairing_code
    if code is None:
        return state, Ignore("pairing code not generated yet")
    if hmac.compare_digest(inbound.text.strip().encode(), code.encode()):
        bound = replace(
            state, owner_open_id=inbound.sender_open_id, pairing_code=None, pair_failures=0
        )
        return bound, Reply("配对成功。之后 agent 的审批和完成通知会发到这里。发 /help 查看用法。")
    failures = state.pair_failures + 1
    if failures >= MAX_PAIR_FAILURES:
        return replace(state, pairing_code=None, pair_failures=0), Ignore(
            "too many wrong pairing codes, code rotated"
        )
    return replace(state, pair_failures=failures), Ignore("wrong pairing code")


def _owner_action(
    inbound: Inbound, state: State, snapshots: Sequence[AgentSnapshot], cfg: Config
) -> Action:
    text = inbound.text.strip()
    if not text:
        return Reply("只支持文本消息。\n" + HELP)

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
        return _act_on_ref(ref, text, live)

    if text.startswith("/"):
        return _command(text, snapshots, cfg)

    outstanding = _outstanding(state, live)
    if len(outstanding) == 1:
        return _act_on_ref(outstanding[0], text, live)
    return Reply(_outstanding_listing(outstanding, live) + "\n\n" + HELP)


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
    tokens = text.lower().split()
    if tokens and all(t in KEY_TOKENS for t in tokens):
        return Keys(s.pane_id, tuple(tokens))
    return Text(s.pane_id, text, then_enter=True)


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
        return Reply(HELP)
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
    return Reply(f"未知命令 {cmd}。\n" + HELP)


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

from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Sequence

from .messages import Messages, messages
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


def help_text(cfg: Config) -> str:
    return messages(cfg.lang).help.format(minutes=cfg.shortcut_minutes)


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
        return state, Reply(messages(cfg.lang).late)
    return state, None


def owner_action(
    inbound: Inbound,
    state: State,
    snapshots: Sequence[AgentSnapshot],
    cfg: Config,
    now: float,
) -> Action:
    m = messages(cfg.lang)
    text = inbound.text.strip()
    if not text:
        return Reply(m.text_only + "\n" + help_text(cfg))

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
            return Reply(m.ref_not_found)
        if ref.kind == "blocked" and text.startswith("/"):
            return _command(text, snapshots, cfg, m)
        if _predates(inbound, ref):
            return Reply(m.late)
        return _act_on_ref(ref, text, live, m)

    if text.startswith("/"):
        return _command(text, snapshots, cfg, m)

    outstanding = _outstanding(state, live, m)
    if len(outstanding) != 1:
        return Reply(_outstanding_listing(outstanding, live, m) + "\n\n" + help_text(cfg))
    ref = outstanding[0]
    if now - ref.sent_at > cfg.shortcut_minutes * 60:
        return Reply(m.shortcut_expired.format(minutes=cfg.shortcut_minutes))
    if _predates(inbound, ref):
        return Reply(m.late)
    return _act_on_ref(ref, text, live, m)


def _predates(inbound: Inbound, ref: MessageRef) -> bool:
    return inbound.created_at is None or inbound.created_at < ref.sent_at


def _guard(
    ref: MessageRef, live: Mapping[str, AgentSnapshot], m: Messages
) -> AgentSnapshot | str:
    s = live.get(ref.terminal_id)
    if s is None:
        return m.agent_gone
    if ref.kind == "blocked":
        ok = s.status == "blocked" and s.state_change_seq == ref.seq
    else:
        ok = s.status in ("idle", "done") and s.completion_seq == ref.seq
    if not ok:
        return m.state_changed.format(name=s.display_name, status=m.status[s.status])
    return s


def _act_on_ref(
    ref: MessageRef, text: str, live: Mapping[str, AgentSnapshot], m: Messages
) -> Action:
    s = _guard(ref, live, m)
    if isinstance(s, str):
        return Reply(s)
    if ref.kind == "done":
        return Prompt(s.pane_id, text)
    if ref.digest is None:
        return Reply(m.no_digest)
    tokens = text.lower().split()
    if tokens and all(t in KEY_TOKENS for t in tokens):
        return Keys(s.pane_id, tuple(tokens), ref.digest)
    for prefix in TEXT_PREFIXES:
        if text.lower().startswith(prefix):
            return Text(s.pane_id, text[len(prefix):], ref.digest)
    return Reply(m.blocked_usage)


def _outstanding(
    state: State, live: Mapping[str, AgentSnapshot], m: Messages
) -> list[MessageRef]:
    latest: dict[str, MessageRef] = {}
    for ref in state.messages.values():
        latest[ref.terminal_id] = ref
    return [r for r in latest.values() if not isinstance(_guard(r, live, m), str)]


def _outstanding_listing(
    refs: Sequence[MessageRef], live: Mapping[str, AgentSnapshot], m: Messages
) -> str:
    if not refs:
        return m.no_outstanding
    lines = [m.outstanding_header]
    for r in refs:
        s = live[r.terminal_id]
        lines.append(
            m.outstanding_line.format(
                workspace=s.workspace_label, name=s.display_name, status=m.status[s.status]
            )
        )
    return "\n".join(lines)


def _command(
    text: str, snapshots: Sequence[AgentSnapshot], cfg: Config, m: Messages
) -> Action:
    parts = text.split(maxsplit=2)
    cmd = parts[0].lower()
    agents = ordered(snapshots)

    if cmd == "/help":
        return Reply(help_text(cfg))
    if cmd == "/list":
        if not agents:
            return Reply(m.no_agents)
        return Reply(
            "\n".join(
                f"{i}. {s.workspace_label} / {s.display_name} [{s.agent}] {m.status[s.status]}"
                for i, s in enumerate(agents, 1)
            )
        )
    if cmd == "/read":
        if len(parts) < 2:
            return Reply(m.usage_read)
        found = _select(parts[1], agents, m)
        if isinstance(found, str):
            return Reply(found)
        return Read(found.pane_id, cfg.read_lines)
    if cmd == "/to":
        if len(parts) < 3:
            return Reply(m.usage_to)
        found = _select(parts[1], agents, m)
        if isinstance(found, str):
            return Reply(found)
        if found.status not in ("idle", "done"):
            return Reply(
                m.to_wrong_status.format(name=found.display_name, status=m.status[found.status])
            )
        return Prompt(found.pane_id, parts[2])
    return Reply(m.unknown_command.format(cmd=cmd) + "\n" + help_text(cfg))


def _select(sel: str, agents: Sequence[AgentSnapshot], m: Messages) -> AgentSnapshot | str:
    if sel.isdigit():
        i = int(sel)
        if 1 <= i <= len(agents):
            return agents[i - 1]
        return m.index_out_of_range.format(sel=sel)
    key = sel.lower()
    hits = [s for s in agents if key in (s.display_name.lower(), s.pane_id.lower())]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        return m.selector_not_found.format(sel=sel)
    return m.selector_ambiguous.format(sel=sel)

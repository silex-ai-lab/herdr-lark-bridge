from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from typing import Any, Protocol, Sequence, cast

from .models import STATUSES, AgentSnapshot, AgentStatus

log = logging.getLogger(__name__)

_STATUS: dict[Any, AgentStatus] = {s: s for s in STATUSES}


class HerdrError(Exception):
    pass


class HerdrPort(Protocol):
    def list_agents(self) -> list[AgentSnapshot]: ...
    def read(self, pane_id: str, lines: int) -> str: ...
    def prompt(self, pane_id: str, text: str) -> None: ...
    def send_keys(self, pane_id: str, keys: Sequence[str]) -> None: ...
    def send_text(self, pane_id: str, text: str) -> None: ...


def parse_agent_list(raw: str, labels: dict[str, str]) -> list[AgentSnapshot]:
    try:
        agents = json.loads(raw)["result"]["agents"]
    except (ValueError, KeyError, TypeError) as e:
        raise HerdrError(f"unexpected agent list output: {e}") from e
    out: list[AgentSnapshot] = []
    for a in cast(list[dict[str, Any]], agents):
        raw_status = a.get("agent_status")
        status = _STATUS.get(raw_status, "unknown")
        try:
            out.append(
                AgentSnapshot(
                    terminal_id=a["terminal_id"],
                    pane_id=a["pane_id"],
                    workspace_id=a["workspace_id"],
                    workspace_label=labels.get(a["workspace_id"]) or a["workspace_id"],
                    agent=a.get("agent", "agent"),
                    status=status,
                    completion_seq=int(a.get("completion_seq", 0)),
                    state_change_seq=int(a.get("state_change_seq", 0)),
                    name=a.get("name") or None,
                    cwd=a.get("cwd", ""),
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            raise HerdrError(f"malformed agent entry: {e}") from e
    return out


def parse_workspace_labels(raw: str) -> dict[str, str]:
    try:
        items = json.loads(raw)["result"]["workspaces"]
        return {w["workspace_id"]: w["label"] for w in items}
    except (ValueError, KeyError, TypeError) as e:
        raise HerdrError(f"unexpected workspace list output: {e}") from e


def find_binary() -> str:
    found = shutil.which("herdr")
    if found:
        return found
    fallback = os.path.expanduser("~/.local/bin/herdr")
    if os.access(fallback, os.X_OK):
        return fallback
    raise HerdrError("herdr binary not found on PATH or at ~/.local/bin/herdr")


class HerdrCli:
    def __init__(self, binary: str | None = None, timeout: float = 15.0) -> None:
        self._binary = binary
        self._timeout = timeout

    def _run(self, *args: str) -> str:
        binary = self._binary or find_binary()
        try:
            p = subprocess.run(
                [binary, *args], capture_output=True, text=True, timeout=self._timeout
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            raise HerdrError(f"herdr {' '.join(args[:2])} failed: {e}") from e
        if p.returncode != 0:
            detail = (p.stderr.strip() or p.stdout.strip())[:500]
            raise HerdrError(f"herdr {' '.join(args[:2])} exited {p.returncode}: {detail}")
        return p.stdout

    def list_agents(self) -> list[AgentSnapshot]:
        agents_raw = self._run("agent", "list")
        try:
            labels = parse_workspace_labels(self._run("workspace", "list"))
        except HerdrError as e:
            log.warning("workspace labels unavailable: %s", e)
            labels = {}
        return parse_agent_list(agents_raw, labels)

    def read(self, pane_id: str, lines: int) -> str:
        return self._run(
            "agent", "read", pane_id, "--source", "recent",
            "--lines", str(lines), "--format", "text",
        )

    def prompt(self, pane_id: str, text: str) -> None:
        self._run("agent", "prompt", pane_id, text)

    def send_keys(self, pane_id: str, keys: Sequence[str]) -> None:
        self._run("agent", "send-keys", pane_id, *keys)

    def send_text(self, pane_id: str, text: str) -> None:
        self._run("pane", "send-text", pane_id, text)

# Resume notes

Last updated 2026-11-18.

## Goal

Herdr agents that need a human (blocked on an approval, or done) send a Lark DM
from a dedicated bot. The owner answers in Lark and the reply goes into that
agent's pane as keys or a prompt. Deterministic, no LLM in the loop. Easy for
other people to install.

## State

- `main` is pushed to `silex-ai-lab/herdr-lark-bridge` (private, MIT). CI is
  green on macOS and Ubuntu at `45a8d3a`.
- Verified live on the author's Mac against real Lark and real agents: pairing,
  blocked notification plus key reply, refusal of a free-text reply to a blocked
  dialog, done notification plus prompt reply, no duplicates across restarts,
  `service install` over a running service, `doctor`, and
  `uv tool install git+https://...` from the remote.
- 210 tests pass locally (`uv run pytest`), pyright strict is clean on `src/`.
  The tests use a fake Herdr and a fake Lark.

## Hard constraints

- Inbound Lark text becomes keystrokes in the owner's terminals. Any change to
  `route.py`, `pairing.py` or the digest check in `daemon.py` needs an
  independent review before it ships.
- A reply to a blocked notification sends key names only, or text behind the
  `输入 ` / `text ` prefix. Never type free text followed by Enter.
- Herdr refuses `agent read --lines N` beyond the visible rows on a blocked
  agent. Blocked reads use `--source visible`.
- `launchctl bootout` is asynchronous. `service install` retries `bootstrap`.
- No real app ids, open ids, home paths or session ids in the repo. The
  `tests/fixtures/agent_list.json` capture is synthetic on purpose.

## Not verified

- Interactive `herdr-lark setup` on a real tty with a brand-new Lark app.
- Feishu China (`LARK_DOMAIN=feishu`) and any Linux run. The background
  service is macOS launchd only.
- English messages (`lang = "en"`) in a real Lark chat.
- The websocket watchdog against a real failed reconnect. An open but dead
  connection is not detected.
- The second and third rounds of changes (review fixes, easy setup) had no
  second independent review.

## Open decisions for the owner

- Make the repository public or keep it private.
- Copyright line in `LICENSE` reads `Silex AI`.

## Next steps

1. Have someone else install from the README on a clean machine and record
   where they get stuck.
2. Before going public: one more independent review of the routing and pairing
   code, and a real-tty run of `herdr-lark setup`.
3. Candidates, none started: Lark card buttons for approvals instead of typed
   keys, a systemd user unit for Linux, re-notify when a blocked dialog changes
   without a state change.

## Where things are

- Reply rules, config keys, security model and limits: `README.md`.
- Pure decision logic: `src/herdr_lark/decide.py` (what to notify) and
  `src/herdr_lark/route.py` (what an inbound message does).
- Shell: `src/herdr_lark/daemon.py`. One engine thread owns all state.
- Health check on an installed machine: `herdr-lark doctor`.

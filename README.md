# herdr-lark-bridge

A small daemon that connects Herdr agents to a Lark bot. When an agent waits for approval or finishes a round, the bot DMs you the screen tail. Your reply goes straight into that agent's pane. No LLM is involved. Routing is deterministic.

## Lark app requirements

Create a custom app on the international Lark Developer Console (open.larksuite.com), then:

- Enable the **Bot** capability.
- Add scopes `im:message.p2p_msg:readonly` and `im:message:send_as_bot`.
- Under Events, use **persistent connection** (long connection) and subscribe to `im.message.receive_v1`.
- Publish a version so the scopes and event take effect.

## Setup

```
mkdir -p ~/.config/herdr-lark
printf 'LARK_APP_ID=cli_xxx\nLARK_APP_SECRET=xxx\n' > ~/.config/herdr-lark/credentials.env
chmod 600 ~/.config/herdr-lark/credentials.env
uv sync
uv run herdr-lark run          # or: scripts/install-launchd.sh
uv run herdr-lark pair-code    # prints a 6-digit code
```

DM the bot the 6-digit code. Its sender becomes the only owner. Every other sender is ignored, because inbound text becomes keystrokes in your terminals. The daemon refuses to start when `credentials.env` is readable by group or others.

`scripts/install-launchd.sh` writes `~/Library/LaunchAgents/com.user.herdr-lark-bridge.plist` and loads it (KeepAlive, logs in `~/Library/Logs/herdr-lark/`). `--dry-run` prints the rendered plist instead.

## When you get a message

- **Blocked** (等待审批): sent after the agent stays blocked for `blocked_delay_seconds` (default 20).
- **Done** (已完成): sent after `done_delay_seconds` (default 60) and only when no agent in the same workspace is still working. Agents already done at the very first start are not announced.

Quote-reply to a message to act on its agent. A plain DM acts on the only outstanding notification, or lists them when there are several.

- Blocked target: a reply made only of key names (`0-9 y n enter esc tab up down left right space`) is sent as key presses. Anything else is typed literally and followed by Enter. Send `1 enter` if a dialog needs both.
- Done target: the text is sent as a new prompt.
- If the agent state changed since the notification, nothing is sent and the bot says 状态已变化.

Commands (plain DMs): `/list`, `/read <n|name>`, `/to <n|name> <text>`, `/help`.

## Config

`~/.config/herdr-lark/config.toml` is optional. Keys: `poll_seconds` (3), `blocked_delay_seconds` (20), `done_delay_seconds` (60), `screen_lines` (40), `read_lines` (40). State lives in `~/.local/state/herdr-lark/state.json`. `HERDR_LARK_CONFIG_DIR` and `HERDR_LARK_STATE_DIR` override both directories.

## Other commands

`herdr-lark status` shows pairing, tracked state and live agents. `herdr-lark send-test` sends a test message to the owner.

## Design notes

Pure functions `decide` (what to notify) and `route` (what an inbound DM does) sit in the middle. Herdr and Lark are adapters behind small interfaces. One engine thread owns all state and consumes a queue. The poll ticker and the Lark websocket callback only enqueue.

## Development

```
uv run pytest
uv run pyright
```

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
uv run herdr-lark pair         # prints a 6-digit code, valid 10 minutes
```

DM the bot the 6-digit code. Its sender becomes the only owner. Every other sender is ignored, because inbound text becomes keystrokes in your terminals. The daemon refuses to start when `credentials.env` is readable by group or others.

Pairing is armed locally and never by the daemon. `herdr-lark pair` writes `~/.config/herdr-lark/pairing.json` (mode 0600) with the code and its expiry. The daemon accepts a pairing DM only while that file exists and has not expired, only in a p2p chat, and only while no owner exists. The file is deleted on success, on expiry and after 5 wrong codes. Nothing re-arms it. `herdr-lark pair` refuses while an owner exists.

The owner lives in `~/.config/herdr-lark/owner` (one line, mode 0600), not in `state.json`. `herdr-lark unpair` deletes it, and a running daemon notices on its next tick or message. `owner_open_id`, `pairing_code` and `pair_failures` left in an old `state.json` are ignored and disappear on the next save.

`scripts/install-launchd.sh` writes `~/Library/LaunchAgents/com.user.herdr-lark-bridge.plist` and loads it (KeepAlive, logs in `~/Library/Logs/herdr-lark/`). `--dry-run` prints the rendered plist instead.

## When you get a message

- **Blocked** (等待审批): sent after the agent stays blocked for `blocked_delay_seconds` (default 20).
- **Done** (已完成): sent after `done_delay_seconds` (default 60), only when a new `completion_seq` appears (greater than the last notified one), and only when no agent in the same workspace is still working. A terminal first seen while already done is recorded as notified and not announced. A done agent without `completion_seq` is skipped with one warning.

Quote-reply to a message to act on its agent.

- **Blocked target.** Only two forms are accepted. A reply made only of key names (`0-9 y n enter esc tab up down left right space`, space separated, for example `1` or `down down enter`) is sent as key presses. A reply that starts with `输入 ` or `text ` (case-insensitive) types the rest literally and presses Enter. Anything else, including `yes`, `no`, `是`, `否`, `不要` and `y.`, sends nothing and the bot explains the two forms. A quoted `/command` runs as a command and is never typed.
- **Blocked target, same dialog check.** The notification stores a digest of the last 15 compacted screen lines. Right before keys or text are sent, the pane is read again. If the digest differs, nothing is sent and the bot posts the fresh screen as a new notification, which you can quote-reply. A screen that changes on its own (a clock, a spinner in the last 15 lines) causes a refusal and a fresh notification, never a wrong send.
- **Done target.** The text is sent as a new prompt. A quoted `/compact` stays literal text.
- If the agent state changed since the notification, nothing is sent and the bot says 状态已变化.
- **Plain DM without quoting** acts on the only outstanding notification, and only when exactly one is outstanding and it was sent within `shortcut_minutes` (default 30). Otherwise the bot lists the outstanding ones.
- **Late messages.** A message whose Lark create time is more than `max_inbound_age_seconds` (default 120) old when it arrives, missing, or older than the notification it would act on, is not executed and the bot says so.
- Text that starts with `--` is safe. Verified against the installed herdr: `agent prompt <target> <text>` takes the first argument after the target as the text even when it looks like an option, and `pane send-text` takes its argument literally. The bridge always passes the text as one argument right after the target. `tests/test_herdr_cli.py` asserts the argv and probes the real binary against a nonexistent target.

Commands (plain DMs): `/list`, `/read <n|name>`, `/to <n|name> <text>`, `/help`.

## Config

`~/.config/herdr-lark/config.toml` is optional. Keys: `poll_seconds` (3), `blocked_delay_seconds` (20), `done_delay_seconds` (60), `screen_lines` (40), `read_lines` (40), `shortcut_minutes` (30), `max_inbound_age_seconds` (120), `prune_after_seconds` (600). State lives in `~/.local/state/herdr-lark/state.json` (directory 0700, file 0600, fsync before rename). A missing state file starts fresh. A corrupt one is moved to `state.json.corrupt-<unix ts>` and the daemon starts fresh. `HERDR_LARK_CONFIG_DIR` and `HERDR_LARK_STATE_DIR` override both directories.

Dedup state for a terminal is dropped only after it has been absent from `agent list` for `prune_after_seconds`, so one empty or partial listing does not cause re-notification.

## Other commands

`herdr-lark status` shows the owner, tracked state and live agents. `herdr-lark send-test` sends a test message to the owner. `herdr-lark pair` and `herdr-lark unpair` manage the owner.

## Limits

- A crash between sending a notification and saving state can send the same notification twice. This is accepted. The reverse order would risk a lost notification.
- A crash after an inbound event is recorded and before its keys are sent drops that input. The event is not retried.
- Typing text is two herdr calls (text, then Enter). The same-dialog check runs before the first.
- The websocket watchdog exits the process (launchd restarts it) when the SDK client holds no connection for 300 seconds. The signal is the SDK's private `_conn` attribute, which is `None` after a failed reconnect leaves the client deaf. A connection object that is open but silently dead is not detected, because the SDK does not expose ping or pong state.
- A failed notification send is retried no sooner than 60 seconds later.
- Blocked notifications saved by an older version have no screen digest, so quoted replies to them are refused until a new notification arrives.

## Design notes

Pure functions `decide` (what to notify) and `route` (what an inbound DM does) sit in the middle. Herdr and Lark are adapters behind small interfaces. One engine thread owns all state and consumes a queue. The poll ticker and the Lark websocket callback only enqueue.

## Development

```
uv run pytest
uv run pyright
```

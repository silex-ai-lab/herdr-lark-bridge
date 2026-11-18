# herdr-lark-bridge

[中文说明](README.zh-CN.md)

Get a Lark DM when a Herdr agent is blocked on an approval or has finished a round. Quote-reply to the DM and your answer goes into that agent's pane as key presses or a prompt.

There is no LLM in the loop. Routing is deterministic, only the paired owner is obeyed, and approvals are key-only.

## Requirements

- macOS for the background service. Linux should work in the foreground but is untested.
- herdr 0.9.3 or newer (the version this was tested with), running.
- [uv](https://docs.astral.sh/uv/) and Python 3.12 or newer (uv installs Python for you).
- A Lark account on the international Lark. Feishu (China) is supported by a setting but untested.

## Quickstart

1. **Create the Lark app.** Open [open.larksuite.com/app](https://open.larksuite.com/app) (Feishu China: [open.feishu.cn/app](https://open.feishu.cn/app)), use the **Built for agents** Create button, and create the app. It preconfigures the bot, the persistent-connection event and the scopes, and publishes the app. Copy the App ID and App Secret from its credentials page.
2. **Install.**
   ```
   uv tool install git+https://github.com/silex-ai-lab/herdr-lark-bridge
   ```
3. **Set up.**
   ```
   herdr-lark setup
   ```
   It asks for the domain, App ID and App Secret (hidden), saves them with mode 0600, checks them against Lark, offers to install the background service, and prints a 6-digit pairing code.
4. **DM the code.** In Lark, open a direct chat with your bot and send the 6-digit code within 10 minutes. The bot replies "Paired". You are now the only owner.
5. **Done.** Run `herdr-lark send-test` for a test message, or let an agent block. If anything looks off, run `herdr-lark doctor`.

`herdr-lark setup` is safe to rerun. It keeps saved values when you press Enter, and it does not arm pairing again while an owner exists.

### Scripted setup

```
LARK_APP_SECRET=... herdr-lark setup --non-interactive --domain lark --app-id cli_xxx --service
```

The secret is read from `LARK_APP_SECRET` or, with `--app-secret-stdin`, from one line of stdin. `LARK_APP_ID` and `LARK_DOMAIN` work as env vars too. Use `--no-service` to skip the service.

## What you get

- **Blocked.** Sent after the agent stays blocked for `blocked_delay_seconds`. It carries the visible screen tail.
- **Done.** Sent after `done_delay_seconds`, only for a new completion, and only when no other agent in the same workspace is still working. An agent first seen already done is recorded and not announced.

## Reply rules

Quote-reply to a notification to act on its agent.

| Target | Reply | Effect |
| --- | --- | --- |
| Blocked | Key names only, space separated (`y n 0-9 enter esc tab up down left right space`), for example `1` or `down down enter` | Sent as key presses |
| Blocked | `text <words>` or `输入 <words>` (case-insensitive prefix) | Types the words as-is and presses Enter |
| Blocked | Anything else, including `yes`, `no`, `y.` | Nothing is sent, the bot explains the two forms |
| Blocked | A quoted `/command` | Runs as a command, never typed |
| Done | Any text | Sent as a new prompt. A quoted `/compact` stays literal text |
| Either | Plain DM without quoting | Acts on the only outstanding notification, if exactly one exists and it is at most `shortcut_minutes` old. Otherwise the bot lists them |

Both prefixes work whatever `lang` is set to. Right before keys or text are sent, the pane is read again and compared with a digest of the notified screen. If it differs, nothing is sent and the bot posts the fresh screen as a new notification. If the agent state changed, nothing is sent. A message older than `max_inbound_age_seconds` is refused.

## Commands

In Lark (plain DMs): `/list`, `/read <n|name>`, `/to <n|name> <text>`, `/help`.

In the terminal:

| Command | Does |
| --- | --- |
| `herdr-lark setup` | Credentials, verification, service, pairing |
| `herdr-lark doctor` | Checks the whole install, one line per check, exit 1 on failure |
| `herdr-lark service install \| uninstall \| status` | Manage the launchd service. `install --dry-run` prints the plist |
| `herdr-lark run` | Run in the foreground |
| `herdr-lark pair` / `unpair` | Arm a pairing code / forget the owner |
| `herdr-lark status` | Owner, tracked state, live agents |
| `herdr-lark send-test` | Send a test DM to the owner |

## Configuration

Files live in `~/.config/herdr-lark/`. State lives in `~/.local/state/herdr-lark/state.json`. `HERDR_LARK_CONFIG_DIR` and `HERDR_LARK_STATE_DIR` override the directories.

`credentials.env` (written by `setup`, must be mode 0600): `LARK_APP_ID`, `LARK_APP_SECRET`, `LARK_DOMAIN` (`lark` or `feishu`, default `lark`).

`config.toml` is optional:

| Key | Default | Meaning |
| --- | --- | --- |
| `lang` | `"zh"` | Language of every message sent to Lark: `"zh"` or `"en"` |
| `poll_seconds` | 3 | Herdr polling interval |
| `blocked_delay_seconds` | 20 | Wait before a blocked notification |
| `done_delay_seconds` | 60 | Wait before a done notification |
| `screen_lines` | 40 | Screen lines per notification |
| `read_lines` | 40 | Lines for `/read` |
| `shortcut_minutes` | 30 | Age limit for replies without quoting |
| `max_inbound_age_seconds` | 120 | Older inbound messages are refused |
| `prune_after_seconds` | 600 | Dedup state is dropped after a terminal is absent this long |

The service reads `config.toml` at start. Restart it with `herdr-lark service install` after editing.

## Security model

- **Owner lock.** Inbound text becomes keystrokes in your terminals, so only one Lark account is obeyed. Every other sender is ignored, and group chats are ignored.
- **Local pairing.** Pairing is armed only on your machine by `herdr-lark setup` or `herdr-lark pair`. It writes a code with a 10 minute expiry. The daemon accepts a pairing DM only while that code is armed, only in a direct chat and only while no owner exists. The code is deleted on success, expiry and after 5 wrong tries. The owner is stored in `owner` (mode 0600).
- **Key-only approvals.** A blocked agent accepts key names or an explicit `text`/`输入` prefix. Natural-language replies such as `yes` are never interpreted.
- **Dialog digest.** Keys are sent only if the dialog on screen is still the one you were shown.
- **Credentials.** The daemon refuses to start when `credentials.env` is readable by group or others.
- **What goes to Lark.** For a blocked agent, the last `screen_lines` lines of its visible screen. For a done agent, the tail of its recent output. `/read` returns the same kind of tail. Each also carries the workspace label, agent name and agent type. Text is cut at 8000 characters. Anything visible in the pane, including secrets, is sent to Lark's servers and stays in the chat history. Your replies and Lark message ids pass through Lark too.

## Limits

- The background service is macOS (launchd) only. On other platforms `herdr-lark service` says so, and `herdr-lark run` works in the foreground. Linux and Feishu China are untested.
- When the laptop sleeps, nothing is polled, so there are no notifications until it wakes.
- A watchdog exits the process (launchd restarts it) when the Lark websocket holds no connection for 300 seconds. A connection that is open but silently dead is not detected.
- A crash between sending a notification and saving state can send the same notification twice. The reverse order could lose one.
- A crash after an inbound event is recorded and before its keys are sent drops that input.
- A failed notification send is retried no sooner than 60 seconds later.

## Troubleshooting

Run `herdr-lark doctor`. It checks the herdr binary and server, credentials and their mode, a live token fetch, the owner, the service and the last log lines, and prints a fix for each failure. Logs are in `~/Library/Logs/herdr-lark/`.

| Symptom | Likely cause |
| --- | --- |
| `setup` fails the token check | Wrong App ID or Secret, wrong domain, or the app is not published |
| Pairing code ignored | Expired, bot not running (`doctor` shows the service), or the DM was not a direct chat |
| No notifications | Laptop asleep, herdr not running, or no owner yet |

## Uninstall

```
herdr-lark service uninstall
uv tool uninstall herdr-lark-bridge
rm -r ~/.config/herdr-lark ~/.local/state/herdr-lark ~/Library/Logs/herdr-lark
```

## Development

```
uv sync
uv run pytest
uv run pyright
```

Tests that need the real `herdr` binary skip when it is absent. Pure functions `decide` (what to notify) and `route` (what a DM does) sit in the middle, with Herdr and Lark as adapters behind small interfaces. One engine thread owns all state. User-facing strings live in `src/herdr_lark/messages.py`, one table per language.

## License

MIT. See [LICENSE](LICENSE).

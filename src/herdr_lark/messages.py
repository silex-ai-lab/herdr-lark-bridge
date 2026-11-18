from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .models import LANGS, AgentStatus, Lang


@dataclass(frozen=True)
class Messages:
    status: Mapping[AgentStatus, str]
    needs_blocked: str
    needs_done: str
    hint_blocked: str
    hint_done: str
    blocked_usage: str
    help: str
    late: str
    no_digest: str
    text_only: str
    ref_not_found: str
    shortcut_expired: str
    agent_gone: str
    state_changed: str
    no_outstanding: str
    outstanding_header: str
    outstanding_line: str
    no_agents: str
    usage_read: str
    usage_to: str
    to_wrong_status: str
    unknown_command: str
    index_out_of_range: str
    selector_not_found: str
    selector_ambiguous: str
    truncated: str
    screen_empty: str
    screen_unreadable: str
    herdr_unavailable: str
    herdr_failed: str
    paired: str
    dialog_changed_note: str
    dialog_changed_reply: str
    latest_screen_sent: str
    use_read: str
    sent: str
    keys_sent: str
    typed_enter: str
    screen_header: str
    test_title: str
    test_text: str
    test_code: str
    test_footer: str


ZH = Messages(
    status={
        "idle": "空闲",
        "working": "工作中",
        "blocked": "等待审批",
        "done": "已完成",
        "unknown": "未知",
    },
    needs_blocked="等待审批",
    needs_done="已完成，等你下一步",
    hint_blocked=(
        "引用回复本消息。按键：只写按键名，如 1、y、down enter（y n 0-9 enter esc tab up down left right space）。"
        "输入文字：以「输入 」或「text 」开头，其后内容原样输入并回车。其他回复（如 yes、no、是、否）不会被执行。"
    ),
    hint_done="引用回复本消息，内容会作为新提示词发送。",
    blocked_usage=(
        "等待审批的 agent 只接受两种回复，其他内容（包括 yes、no、是、否）不会被执行：\n"
        "1. 按键：只写按键名，空格分隔，可多个，例如 1 或 down down enter。"
        "可用 y n 0-9 enter esc tab up down left right space。\n"
        "2. 输入文字：以「输入 」或「text 」开头，其后的内容原样输入并回车。\n"
        "未执行任何操作。"
    ),
    help=(
        "用法\n"
        "回复(引用)某条通知，内容会送进对应的 agent。\n"
        "等待审批：只含按键名（y n 0-9 enter esc tab up down left right space）时按键发送；"
        "「输入 文字」或「text 文字」会原样输入后回车；其他内容不会执行。\n"
        "已完成：内容作为新提示词发送。\n"
        "不引用直接发文字：仅当只有一条待处理通知且发出不超过 {minutes:g} 分钟时生效。\n"
        "命令：/list，/read <编号或名称>，/to <编号或名称> <文字>，/help"
    ),
    late="这条消息到达过晚（或缺少发送时间），为安全起见未执行。请重新发送。",
    no_digest="这条通知没有记录当时的屏幕内容，无法确认对话框是否一致，未执行。请等待新的通知。",
    text_only="只支持文本消息。",
    ref_not_found="找不到这条消息对应的通知，可能已过期。发 /list 查看当前 agent。",
    shortcut_expired=(
        "最近一条通知已超过 {minutes:g} 分钟，不再接受不引用的回复。请引用回复通知，或发 /list。"
    ),
    agent_gone="该 agent 已不存在。",
    state_changed="状态已变化，{name} 当前状态：{status}。未执行任何操作。",
    no_outstanding="当前没有待处理的通知。",
    outstanding_header="有多条待处理通知，请引用回复其中一条：",
    outstanding_line="- {workspace} / {name}：{status}",
    no_agents="当前没有 agent。",
    usage_read="用法：/read <编号或名称>",
    usage_to="用法：/to <编号或名称> <文字>",
    to_wrong_status="{name} 当前状态：{status}，只能给空闲或已完成的 agent 发送。",
    unknown_command="未知命令 {cmd}。",
    index_out_of_range="编号 {sel} 超出范围，发 /list 查看。",
    selector_not_found="找不到 {sel}，发 /list 查看。",
    selector_ambiguous="{sel} 匹配多个 agent，请用编号。",
    truncated="…(已截断)",
    screen_empty="(屏幕为空)",
    screen_unreadable="(无法读取屏幕：{error})",
    herdr_unavailable="herdr 不可用：{error}",
    herdr_failed="herdr 执行失败：{error}",
    paired="配对成功。之后 agent 的审批和完成通知会发到这里。发 /help 查看用法。",
    dialog_changed_note="对话框已变化，你刚才的回复没有执行。请看下面的最新屏幕，并引用回复这条新消息。",
    dialog_changed_reply="对话框已变化，未执行任何操作。",
    latest_screen_sent="已发送最新屏幕。",
    use_read="发 /read 查看当前屏幕。",
    sent="已发送。",
    keys_sent="已发送按键：{keys}",
    typed_enter="已输入并回车。",
    screen_header="屏幕内容：",
    test_title="herdr-lark 测试",
    test_text="测试消息，桥接已连通。",
    test_code="echo hello",
    test_footer="可以直接回复本消息试试。",
)

EN = Messages(
    status={
        "idle": "idle",
        "working": "working",
        "blocked": "needs approval",
        "done": "done",
        "unknown": "unknown",
    },
    needs_blocked="Needs approval",
    needs_done="Done, waiting for your next step",
    hint_blocked=(
        "Quote-reply to this message. Keys: write key names only, such as 1, y, down enter "
        "(y n 0-9 enter esc tab up down left right space). "
        "Text: start with \"text \" or \"输入 \" and the rest is typed as-is, then Enter. "
        "Any other reply (yes, no, ...) is not executed."
    ),
    hint_done="Quote-reply to this message. Your text is sent as a new prompt.",
    blocked_usage=(
        "A blocked agent accepts two kinds of reply. Anything else, including yes and no, is not executed:\n"
        "1. Keys: write key names only, space separated, for example 1 or down down enter. "
        "Allowed: y n 0-9 enter esc tab up down left right space.\n"
        "2. Text: start with \"text \" or \"输入 \"; the rest is typed as-is, then Enter.\n"
        "Nothing was done."
    ),
    help=(
        "Usage\n"
        "Quote-reply to a notification and your reply goes into that agent.\n"
        "Blocked: key names only (y n 0-9 enter esc tab up down left right space) are sent as key presses; "
        "\"text <words>\" or \"输入 <words>\" types the words as-is and presses Enter; anything else is not executed.\n"
        "Done: your text is sent as a new prompt.\n"
        "A reply without quoting works only when exactly one notification is outstanding "
        "and it was sent within {minutes:g} minutes.\n"
        "Commands: /list, /read <number|name>, /to <number|name> <text>, /help"
    ),
    late="This message arrived too late (or has no send time), so it was not executed for safety. Please send it again.",
    no_digest=(
        "This notification did not record the screen at the time, so the dialog cannot be confirmed. "
        "Nothing was done. Wait for a new notification."
    ),
    text_only="Only text messages are supported.",
    ref_not_found="No notification matches this message, it may have expired. Send /list to see current agents.",
    shortcut_expired=(
        "The latest notification is older than {minutes:g} minutes, so unquoted replies are no longer accepted. "
        "Quote-reply to a notification, or send /list."
    ),
    agent_gone="That agent no longer exists.",
    state_changed="State changed. {name} is now: {status}. Nothing was done.",
    no_outstanding="No outstanding notifications.",
    outstanding_header="Several notifications are outstanding. Quote-reply to one of them:",
    outstanding_line="- {workspace} / {name}: {status}",
    no_agents="No agents.",
    usage_read="Usage: /read <number|name>",
    usage_to="Usage: /to <number|name> <text>",
    to_wrong_status="{name} is {status}. You can only send to an idle or done agent.",
    unknown_command="Unknown command {cmd}.",
    index_out_of_range="Number {sel} is out of range. Send /list.",
    selector_not_found="No agent matches {sel}. Send /list.",
    selector_ambiguous="{sel} matches several agents. Use the number.",
    truncated="...(truncated)",
    screen_empty="(screen is empty)",
    screen_unreadable="(cannot read the screen: {error})",
    herdr_unavailable="herdr unavailable: {error}",
    herdr_failed="herdr command failed: {error}",
    paired="Paired. Approval and completion notifications for your agents will arrive here. Send /help for usage.",
    dialog_changed_note=(
        "The dialog changed and your last reply was not executed. "
        "See the latest screen below and quote-reply to this new message."
    ),
    dialog_changed_reply="The dialog changed. Nothing was done.",
    latest_screen_sent="The latest screen was sent.",
    use_read="Send /read to see the current screen.",
    sent="Sent.",
    keys_sent="Keys sent: {keys}",
    typed_enter="Typed and pressed Enter.",
    screen_header="Screen:",
    test_title="herdr-lark test",
    test_text="Test message. The bridge is connected.",
    test_code="echo hello",
    test_footer="Try quote-replying to this message.",
)

TABLE: Mapping[Lang, Messages] = {"zh": ZH, "en": EN}
assert set(TABLE) == set(LANGS)


def messages(lang: Lang) -> Messages:
    return TABLE[lang]

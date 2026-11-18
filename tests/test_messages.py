import re
import string
from dataclasses import fields

import pytest

from herdr_lark.messages import EN, TABLE, ZH, Messages
from herdr_lark.models import LANGS, Config, Inbound, Keys, Reply, Text
from herdr_lark.models import MessageRef, State

from helpers import snap
from herdr_lark.route import owner_action

CJK = re.compile(r"[一-鿿]")


def placeholders(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def strings(m: Messages) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in fields(Messages):
        v = getattr(m, f.name)
        if isinstance(v, str):
            out[f.name] = v
        else:
            out.update({f"{f.name}.{k}": s for k, s in v.items()})
    return out


def test_every_language_has_a_table_entry():
    assert set(TABLE) == set(LANGS)


def test_languages_use_the_same_placeholders_in_every_message():
    zh, en = strings(ZH), strings(EN)
    assert zh.keys() == en.keys()
    for key in zh:
        assert placeholders(zh[key]) == placeholders(en[key]), key


def test_english_messages_contain_chinese_only_as_the_input_prefix():
    for key, text in strings(EN).items():
        assert not CJK.search(text.replace("输入 ", "")), key


def test_chinese_messages_are_not_english_copies():
    zh, en = strings(ZH), strings(EN)
    same = [k for k in zh if zh[k] == en[k]]
    assert same == ["test_code"]


def blocked_state() -> State:
    return State(messages={"om_n": MessageRef("t1", "blocked", 1, "dg", 1000.0)})


def ask(text: str, lang: str):
    cfg = Config(lang="en" if lang == "en" else "zh")
    inbound = Inbound("e", "om_in", "ou", "p2p", text, parent_id="om_n", created_at=1001.0)
    s = snap("t1", "blocked", state_change_seq=1)
    return owner_action(inbound, blocked_state(), [s], cfg, 1001.0)


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize(
    "text,expected",
    [("输入 use option B", "use option B"), ("text use option B", "use option B"), ("TEXT use option B", "use option B")],
)
def test_text_prefixes_work_in_both_languages(lang: str, text: str, expected: str):
    act = ask(text, lang)
    assert isinstance(act, Text) and act.text == expected


@pytest.mark.parametrize("lang", LANGS)
def test_keys_work_in_both_languages(lang: str):
    assert isinstance(ask("down enter", lang), Keys)


def test_unrecognised_blocked_reply_is_explained_in_the_configured_language():
    zh, en = ask("yes", "zh"), ask("yes", "en")
    assert zh == Reply(ZH.blocked_usage) and en == Reply(EN.blocked_usage)


def test_english_help_and_status_names():
    inbound = Inbound("e", "om_in", "ou", "p2p", "/list", created_at=1001.0)
    act = owner_action(inbound, State(), [snap("t1", "blocked")], Config(lang="en"), 1001.0)
    assert isinstance(act, Reply) and "needs approval" in act.text


def test_english_notification_is_rendered_from_the_table():
    from herdr_lark.models import Notification
    from herdr_lark.render import render_notification

    n = Notification(snap("t1", "blocked"), "blocked", 1)
    out = render_notification(n, "Proceed?", 40, EN)
    assert "Needs approval" in out.text and out.footer == EN.hint_blocked
    assert out.title == "alpha: Needs approval"

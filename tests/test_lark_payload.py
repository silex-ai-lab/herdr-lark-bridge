import json

from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

from herdr_lark.lark import build_post, parse_event
from herdr_lark.models import Outbound


def test_post_payload_has_code_block_and_footer():
    body = json.loads(build_post(Outbound("T", "head", "a\nb", "hint")))
    rows = body["zh_cn"]["content"]
    assert body["zh_cn"]["title"] == "T"
    assert rows[1] == [{"tag": "code_block", "language": "TEXT", "text": "a\nb"}]
    assert rows[2][0]["text"] == "hint"


def test_post_without_code():
    rows = json.loads(build_post(Outbound(None, "hi")))["zh_cn"]["content"]
    assert rows == [[{"tag": "text", "text": "hi"}]]


def event(**message: str) -> P2ImMessageReceiveV1:
    base = {"message_id": "om_1", "chat_type": "p2p", "message_type": "text",
            "content": json.dumps({"text": "hi"})}
    return P2ImMessageReceiveV1({
        "header": {"event_id": "ev_1"},
        "event": {"sender": {"sender_id": {"open_id": "ou_1"}}, "message": {**base, **message}},
    })


def test_parse_event_reads_text_and_reply_ids():
    i = parse_event(event(parent_id="om_p", root_id="om_r"))
    assert i is not None
    assert (i.event_id, i.sender_open_id, i.text, i.parent_id, i.root_id, i.chat_type) == (
        "ev_1", "ou_1", "hi", "om_p", "om_r", "p2p")


def test_parse_event_non_text_has_empty_text():
    i = parse_event(event(message_type="image", content="{}"))
    assert i is not None and i.text == ""


def test_parse_event_reads_create_time_milliseconds_as_seconds():
    for raw in ("1700000000123", 1700000000123):
        i = parse_event(event(create_time=raw))  # type: ignore[arg-type]
        assert i is not None and i.created_at == 1700000000.123


def test_parse_event_without_or_with_garbage_create_time_has_none():
    i = parse_event(event())
    assert i is not None and i.created_at is None
    i = parse_event(event(create_time="soon"))
    assert i is not None and i.created_at is None


def test_lark_sdk_logs_at_warning_so_websocket_url_is_not_logged():
    import logging

    from herdr_lark.lark import LarkClient

    LarkClient("cli_x", "secret")
    assert logging.getLogger("Lark").level == logging.WARNING

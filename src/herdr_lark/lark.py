from __future__ import annotations

import json
import logging
from typing import Callable, Protocol

import lark_oapi as lark  # pyright: ignore[reportMissingTypeStubs]
from lark_oapi.api.im.v1 import (  # pyright: ignore[reportMissingTypeStubs]
    CreateMessageRequest,
    CreateMessageRequestBody,
    P2ImMessageReceiveV1,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)

from .models import Inbound, Outbound

log = logging.getLogger(__name__)


class LarkError(Exception):
    pass


class LarkTransport(Protocol):
    def send_to_user(self, open_id: str, out: Outbound) -> str: ...
    def reply(self, message_id: str, out: Outbound) -> str: ...


def build_post(out: Outbound) -> str:
    rows: list[list[dict[str, str]]] = [[{"tag": "text", "text": out.text}]]
    if out.code is not None:
        rows.append([{"tag": "code_block", "language": "TEXT", "text": out.code}])
    if out.footer:
        rows.append([{"tag": "text", "text": out.footer}])
    return json.dumps({"zh_cn": {"title": out.title or "", "content": rows}}, ensure_ascii=False)


def parse_event(data: P2ImMessageReceiveV1) -> Inbound | None:
    ev = data.event
    if ev is None or ev.message is None or ev.sender is None:
        return None
    msg = ev.message
    sender = ev.sender.sender_id.open_id if ev.sender.sender_id else None
    if not msg.message_id or not sender:
        return None
    text = ""
    if msg.message_type == "text" and msg.content:
        try:
            text = str(json.loads(msg.content).get("text", ""))
        except ValueError:
            text = ""
    event_id = data.header.event_id if data.header and data.header.event_id else msg.message_id
    return Inbound(
        event_id=event_id,
        message_id=msg.message_id,
        sender_open_id=sender,
        chat_type=msg.chat_type or "",
        text=text,
        parent_id=msg.parent_id or None,
        root_id=msg.root_id or None,
    )


class LarkClient:
    def __init__(self, app_id: str, app_secret: str) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        client = (
            lark.Client.builder()
            .app_id(app_id)
            .app_secret(app_secret)
            .domain(lark.LARK_DOMAIN)
            .build()
        )
        assert client.im is not None
        self._messages = client.im.v1.message

    def send_to_user(self, open_id: str, out: Outbound) -> str:
        req = (
            CreateMessageRequest.builder()
            .receive_id_type("open_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(open_id)
                .msg_type("post")
                .content(build_post(out))
                .build()
            )
            .build()
        )
        resp = self._messages.create(req)
        if not resp.success() or resp.data is None or not resp.data.message_id:
            raise LarkError(f"send failed: code={resp.code} msg={resp.msg}")
        return resp.data.message_id

    def reply(self, message_id: str, out: Outbound) -> str:
        req = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .msg_type("post")
                .content(build_post(out))
                .build()
            )
            .build()
        )
        resp = self._messages.reply(req)
        if not resp.success() or resp.data is None or not resp.data.message_id:
            raise LarkError(f"reply failed: code={resp.code} msg={resp.msg}")
        return resp.data.message_id

    def listen(self, on_inbound: Callable[[Inbound], None]) -> None:
        def handler(data: P2ImMessageReceiveV1) -> None:
            inbound = parse_event(data)
            if inbound is None:
                log.warning("dropped malformed im.message.receive_v1 event")
                return
            on_inbound(inbound)

        dispatcher = (
            lark.EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(handler)
            .build()
        )
        ws = lark.ws.Client(
            self._app_id,
            self._app_secret,
            event_handler=dispatcher,
            domain=lark.LARK_DOMAIN,
            log_level=lark.LogLevel.INFO,
        )
        ws.start()

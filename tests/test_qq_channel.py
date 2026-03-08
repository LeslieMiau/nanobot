from types import SimpleNamespace

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.qq import QQ_MAX_MESSAGE_LEN, QQChannel
from nanobot.config.schema import QQConfig


class _FakeAPI:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def post_c2c_message(self, **kwargs) -> None:
        self.calls.append(kwargs)


def _make_channel() -> tuple[QQChannel, _FakeAPI]:
    channel = QQChannel(
        QQConfig(enabled=True, app_id="app", secret="secret", allow_from=["*"]),
        MessageBus(),
    )
    api = _FakeAPI()
    channel._client = SimpleNamespace(api=api)
    return channel, api


@pytest.mark.asyncio
async def test_send_uses_metadata_message_id() -> None:
    channel, api = _make_channel()

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="user_openid",
            content="hello",
            metadata={"message_id": "msg-1"},
        )
    )

    assert len(api.calls) == 1
    assert api.calls[0]["openid"] == "user_openid"
    assert api.calls[0]["content"] == "hello"
    assert api.calls[0]["msg_id"] == "msg-1"
    assert api.calls[0]["msg_type"] == 0


@pytest.mark.asyncio
async def test_send_falls_back_to_reply_to_when_metadata_missing() -> None:
    channel, api = _make_channel()

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="user_openid",
            content="hello",
            reply_to="reply-1",
        )
    )

    assert len(api.calls) == 1
    assert api.calls[0]["msg_id"] == "reply-1"


@pytest.mark.asyncio
async def test_send_generates_msg_id_when_none_provided() -> None:
    channel, api = _make_channel()

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="user_openid",
            content="hello",
        )
    )

    assert len(api.calls) == 1
    assert str(api.calls[0]["msg_id"]).startswith("nanobot-")


@pytest.mark.asyncio
async def test_send_splits_long_message_and_increments_seq() -> None:
    channel, api = _make_channel()
    content = "a" * (QQ_MAX_MESSAGE_LEN + 32)

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="user_openid",
            content=content,
            metadata={"message_id": "msg-1"},
        )
    )

    assert len(api.calls) == 2
    assert all(call["msg_id"] == "msg-1" for call in api.calls)
    seqs = [int(call["msg_seq"]) for call in api.calls]
    assert seqs[1] == seqs[0] + 1
    assert len(str(api.calls[0]["content"])) == QQ_MAX_MESSAGE_LEN
    assert len(str(api.calls[1]["content"])) == 32


@pytest.mark.asyncio
async def test_send_skips_empty_content_when_only_media_present() -> None:
    channel, api = _make_channel()

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="user_openid",
            content="",
            media=["/tmp/a.png"],
        )
    )

    assert api.calls == []

from types import SimpleNamespace

import pytest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.qq import QQ_MAX_MESSAGE_LEN, QQChannel
from nanobot.config.schema import QQConfig


class _FakeApi:
    def __init__(self) -> None:
        self.c2c_calls: list[dict] = []
        self.group_calls: list[dict] = []

    async def post_c2c_message(self, **kwargs) -> None:
        self.c2c_calls.append(kwargs)

    async def post_group_message(self, **kwargs) -> None:
        self.group_calls.append(kwargs)


class _FakeClient:
    def __init__(self) -> None:
        self.api = _FakeApi()


def _make_channel() -> tuple[QQChannel, _FakeClient]:
    channel = QQChannel(
        QQConfig(enabled=True, app_id="app", secret="secret", allow_from=["*"]),
        MessageBus(),
    )
    client = _FakeClient()
    channel._client = client
    return channel, client


@pytest.mark.asyncio
async def test_on_group_message_routes_to_group_chat_id() -> None:
    channel = QQChannel(QQConfig(app_id="app", secret="secret", allow_from=["user1"]), MessageBus())

    data = SimpleNamespace(
        id="msg1",
        content="hello",
        group_openid="group123",
        author=SimpleNamespace(member_openid="user1"),
    )

    await channel._on_message(data, is_group=True)

    msg = await channel.bus.consume_inbound()
    assert msg.sender_id == "user1"
    assert msg.chat_id == "group123"


@pytest.mark.asyncio
async def test_send_group_message_uses_group_api_with_msg_seq() -> None:
    channel, client = _make_channel()
    channel._chat_type_cache["group123"] = "group"

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="group123",
            content="hello",
            metadata={"message_id": "msg1"},
        )
    )

    assert len(client.api.group_calls) == 1
    call = client.api.group_calls[0]
    assert call["group_openid"] == "group123"
    assert call["msg_id"] == "msg1"
    assert call["msg_seq"] == 2
    assert not client.api.c2c_calls


@pytest.mark.asyncio
async def test_send_uses_metadata_message_id_for_c2c() -> None:
    channel, client = _make_channel()

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="user_openid",
            content="hello",
            metadata={"message_id": "msg-1"},
        )
    )

    assert len(client.api.c2c_calls) == 1
    assert client.api.c2c_calls[0]["openid"] == "user_openid"
    assert client.api.c2c_calls[0]["content"] == "hello"
    assert client.api.c2c_calls[0]["msg_id"] == "msg-1"
    assert client.api.c2c_calls[0]["msg_type"] == 0


@pytest.mark.asyncio
async def test_send_falls_back_to_reply_to_when_metadata_missing() -> None:
    channel, client = _make_channel()

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="user_openid",
            content="hello",
            reply_to="reply-1",
        )
    )

    assert len(client.api.c2c_calls) == 1
    assert client.api.c2c_calls[0]["msg_id"] == "reply-1"


@pytest.mark.asyncio
async def test_send_generates_msg_id_when_none_provided() -> None:
    channel, client = _make_channel()

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="user_openid",
            content="hello",
        )
    )

    assert len(client.api.c2c_calls) == 1
    assert str(client.api.c2c_calls[0]["msg_id"]).startswith("nanobot-")


@pytest.mark.asyncio
async def test_send_splits_long_message_and_increments_seq() -> None:
    channel, client = _make_channel()
    content = "a" * (QQ_MAX_MESSAGE_LEN + 32)

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="user_openid",
            content=content,
            metadata={"message_id": "msg-1"},
        )
    )

    assert len(client.api.c2c_calls) == 2
    assert all(call["msg_id"] == "msg-1" for call in client.api.c2c_calls)
    seqs = [int(call["msg_seq"]) for call in client.api.c2c_calls]
    assert seqs[1] == seqs[0] + 1
    assert len(str(client.api.c2c_calls[0]["content"])) == QQ_MAX_MESSAGE_LEN
    assert len(str(client.api.c2c_calls[1]["content"])) == 32


@pytest.mark.asyncio
async def test_send_skips_empty_content_when_only_media_present() -> None:
    channel, client = _make_channel()

    await channel.send(
        OutboundMessage(
            channel="qq",
            chat_id="user_openid",
            content="",
            media=["/tmp/a.png"],
        )
    )

    assert client.api.c2c_calls == []
    assert client.api.group_calls == []

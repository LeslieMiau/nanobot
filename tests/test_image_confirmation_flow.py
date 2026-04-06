from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nanobot.agent.loop import AgentLoop
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.config.schema import ImageGenerationConfig
from nanobot.providers.base import LLMProvider, LLMResponse


class _Provider(LLMProvider):
    async def chat(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
    ) -> LLMResponse:
        return LLMResponse(content="ok")

    def get_default_model(self) -> str:
        return "dummy"


def _make_loop(workspace: Path) -> AgentLoop:
    return AgentLoop(
        bus=MessageBus(),
        provider=_Provider(),
        workspace=workspace,
        model="dummy",
        max_iterations=1,
        image_config=ImageGenerationConfig(),
    )


@pytest.mark.asyncio
async def test_image_confirm_generates_current_item_and_advances_queue(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    loop._set_tool_context("cli", "direct")
    tool = loop.tools.get("image_generate")
    assert tool is not None

    await tool.execute(
        action="stage",
        prompt="prompt one",
        output_path="generated/one.png",
        title="图1",
        card_index=1,
    )
    await tool.execute(
        action="stage",
        prompt="prompt two",
        output_path="generated/two.png",
        title="图2",
        card_index=2,
    )

    original_execute = tool.execute

    async def fake_execute(**kwargs):
        if kwargs["action"] == "generate":
            return json.dumps(
                {
                    "status": "ok",
                    "file_path": str(tmp_path / "generated" / "one.png"),
                    "prompt": kwargs["prompt"],
                    "model": "gpt-image-1",
                    "provider": "openai-compatible",
                },
                ensure_ascii=False,
            )
        return await original_execute(**kwargs)

    tool.execute = AsyncMock(side_effect=fake_execute)

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/image-confirm")
    )

    assert out is not None
    assert "Generated image 1/2" in out.content
    assert "图2" in out.content
    session = loop.sessions.get_or_create("cli:direct")
    queue = session.metadata["image_generation_queue"]["items"]
    assert queue[0]["status"] == "generated"
    assert queue[1]["status"] == "pending"


@pytest.mark.asyncio
async def test_image_edit_updates_prompt_and_re_shows_preview(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    loop._set_tool_context("cli", "direct")
    tool = loop.tools.get("image_generate")
    assert tool is not None

    await tool.execute(
        action="stage",
        prompt="original prompt",
        output_path="generated/one.png",
        title="图1",
        card_index=1,
    )

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/image-edit 改成更损友一点")
    )

    assert out is not None
    assert "Revision request: 改成更损友一点" in out.content
    session = loop.sessions.get_or_create("cli:direct")
    prompt = session.metadata["image_generation_queue"]["items"][0]["prompt"]
    assert "Revision request: 改成更损友一点" in prompt


@pytest.mark.asyncio
async def test_image_skip_marks_item_and_moves_to_next(tmp_path: Path) -> None:
    loop = _make_loop(tmp_path)
    loop._set_tool_context("cli", "direct")
    tool = loop.tools.get("image_generate")
    assert tool is not None

    await tool.execute(
        action="stage",
        prompt="prompt one",
        output_path="generated/one.png",
        title="图1",
        card_index=1,
    )
    await tool.execute(
        action="stage",
        prompt="prompt two",
        output_path="generated/two.png",
        title="图2",
        card_index=2,
    )

    out = await loop._process_message(
        InboundMessage(channel="cli", sender_id="u1", chat_id="direct", content="/image-skip")
    )

    assert out is not None
    assert "Skipped image 1/2" in out.content
    assert "图2" in out.content
    session = loop.sessions.get_or_create("cli:direct")
    items = session.metadata["image_generation_queue"]["items"]
    assert items[0]["status"] == "skipped"
    assert items[1]["status"] == "pending"

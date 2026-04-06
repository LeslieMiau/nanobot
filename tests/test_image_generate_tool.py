from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from nanobot.agent.tools.image_generate import ImageGenerateTool
from nanobot.config.schema import Config
from nanobot.config.schema import ImageGenerationConfig


@pytest.mark.asyncio
async def test_image_generate_stage_uses_callback(tmp_path: Path) -> None:
    staged: list[dict] = []

    async def stage_callback(payload: dict) -> str:
        staged.append(payload)
        return "preview"

    tool = ImageGenerateTool(
        workspace=tmp_path,
        config=ImageGenerationConfig(),
        stage_callback=stage_callback,
    )
    tool.set_context("cli", "direct")

    result = await tool.execute(
        action="stage",
        prompt="draw TradingCat",
        output_path="images/cat.png",
        title="封面",
        card_index=1,
    )

    assert result == "preview"
    assert staged[0]["prompt"] == "draw TradingCat"
    assert staged[0]["output_path"] == "images/cat.png"
    assert staged[0]["channel"] == "cli"
    assert staged[0]["chat_id"] == "direct"


@pytest.mark.asyncio
async def test_image_generate_requires_enabled_config(tmp_path: Path) -> None:
    tool = ImageGenerateTool(
        workspace=tmp_path,
        config=ImageGenerationConfig(enabled=False),
    )

    result = await tool.execute(
        action="generate",
        prompt="draw TradingCat",
        output_path="images/cat.png",
    )

    assert result == "Error: image generation is disabled in config"


@pytest.mark.asyncio
async def test_image_generate_writes_image_and_returns_metadata(tmp_path: Path) -> None:
    png_bytes = b"\x89PNG\r\n\x1a\nfake"
    fake_response = SimpleNamespace(
        data=[SimpleNamespace(b64_json=base64.b64encode(png_bytes).decode("ascii"))]
    )
    fake_client = SimpleNamespace(images=SimpleNamespace(generate=AsyncMock(return_value=fake_response)))

    with patch("nanobot.agent.tools.image_generate.AsyncOpenAI", return_value=fake_client):
        tool = ImageGenerateTool(
            workspace=tmp_path,
            config=ImageGenerationConfig(
                enabled=True,
                provider="openai-compatible",
                model="gpt-image-1",
                api_key="test-key",
            ),
        )
        result = await tool.execute(
            action="generate",
            prompt="draw TradingCat",
            output_path="images/cat.png",
            aspect_ratio="3:4",
            style_preset="xiaohongshu-card",
        )

    payload = json.loads(result)
    assert payload["status"] == "ok"
    assert payload["model"] == "gpt-image-1"
    assert payload["provider"] == "openai-compatible"
    assert Path(payload["file_path"]).read_bytes() == png_bytes
    assert "Style preset: xiaohongshu-card" in payload["prompt"]


def test_image_generation_config_defaults_are_available() -> None:
    config = Config()

    assert config.tools.images.enabled is False
    assert config.tools.images.model == "gpt-image-1"
    assert config.tools.images.default_aspect_ratio == "3:4"

"""Image generation tool with preview-first staging support."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from openai import AsyncOpenAI

from nanobot.agent.tools.base import Tool


class ImageGenerateTool(Tool):
    """Stage or generate images via an OpenAI-compatible image API."""

    def __init__(
        self,
        *,
        workspace: Path,
        config: Any,
        stage_callback: Callable[[dict[str, Any]], Awaitable[str]] | None = None,
    ):
        self.workspace = workspace
        self.config = config
        self._stage_callback = stage_callback
        self._default_channel = ""
        self._default_chat_id = ""

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the current session routing context."""
        self._default_channel = channel
        self._default_chat_id = chat_id

    @property
    def name(self) -> str:
        return "image_generate"

    @property
    def description(self) -> str:
        return (
            "Stage an image prompt for user confirmation, or generate an image after confirmation "
            "using the configured OpenAI-compatible image model."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["stage", "generate"],
                    "description": "Whether to stage a prompt for approval or generate the image immediately.",
                },
                "prompt": {"type": "string", "minLength": 1},
                "output_path": {"type": "string", "minLength": 1},
                "size": {"type": "string"},
                "aspect_ratio": {"type": "string"},
                "style_preset": {"type": "string"},
                "negative_prompt": {"type": "string"},
                "title": {"type": "string"},
                "overlay_text": {"type": "string"},
                "role_name": {"type": "string"},
                "platform": {"type": "string"},
                "content_pack_id": {"type": "string"},
                "card_index": {"type": "integer", "minimum": 1},
            },
            "required": ["action", "prompt", "output_path"],
        }

    async def execute(
        self,
        *,
        action: str,
        prompt: str,
        output_path: str,
        size: str | None = None,
        aspect_ratio: str | None = None,
        style_preset: str | None = None,
        negative_prompt: str | None = None,
        title: str | None = None,
        overlay_text: str | None = None,
        role_name: str | None = None,
        platform: str | None = None,
        content_pack_id: str | None = None,
        card_index: int | None = None,
        **_: Any,
    ) -> str:
        if action == "stage":
            if not self._stage_callback:
                return "Error: Image staging is not configured"
            return await self._stage_callback(
                {
                    "prompt": prompt,
                    "output_path": output_path,
                    "size": size or "",
                    "aspect_ratio": aspect_ratio or "",
                    "style_preset": style_preset or "",
                    "negative_prompt": negative_prompt or "",
                    "title": title or "",
                    "overlay_text": overlay_text or "",
                    "role_name": role_name or "",
                    "platform": platform or "",
                    "content_pack_id": content_pack_id or "",
                    "card_index": card_index,
                    "channel": self._default_channel,
                    "chat_id": self._default_chat_id,
                }
            )

        if not getattr(self.config, "enabled", False):
            return "Error: image generation is disabled in config"
        if not getattr(self.config, "api_key", ""):
            return "Error: image generation api_key is missing"
        if not getattr(self.config, "model", ""):
            return "Error: image generation model is missing"

        final_prompt = prompt.strip()
        if style_preset:
            final_prompt += f"\n\nStyle preset: {style_preset.strip()}"
        if negative_prompt:
            final_prompt += f"\n\nAvoid: {negative_prompt.strip()}"

        resolved_output = self._resolve_output_path(output_path)
        resolved_output.parent.mkdir(parents=True, exist_ok=True)
        resolved_size = size or self._size_for_aspect_ratio(aspect_ratio)
        client = AsyncOpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url or None,
        )

        try:
            response = await client.images.generate(
                model=self.config.model,
                prompt=final_prompt,
                size=resolved_size,
            )
        except Exception as e:
            return f"Error: image generation failed: {e}"

        try:
            await self._write_image_response(response, resolved_output)
        except Exception as e:
            return f"Error: failed to save generated image: {e}"

        return json.dumps(
            {
                "status": "ok",
                "file_path": str(resolved_output),
                "prompt": final_prompt,
                "model": self.config.model,
                "provider": self.config.provider,
                "size": resolved_size,
            },
            ensure_ascii=False,
        )

    def _resolve_output_path(self, output_path: str) -> Path:
        path = Path(output_path).expanduser()
        if not path.is_absolute():
            path = self.workspace / path
        return path

    def _size_for_aspect_ratio(self, aspect_ratio: str | None) -> str:
        if getattr(self.config, "default_size", ""):
            default_size = self.config.default_size
        else:
            default_size = "1024x1536"
        if not aspect_ratio:
            return default_size
        normalized = aspect_ratio.strip().lower()
        return {
            "1:1": "1024x1024",
            "3:4": "1024x1536",
            "4:3": "1536x1024",
            "16:9": "1536x1024",
            "9:16": "1024x1536",
        }.get(normalized, default_size)

    async def _write_image_response(self, response: Any, output_path: Path) -> None:
        if not getattr(response, "data", None):
            raise RuntimeError("provider returned no image data")
        first = response.data[0]
        if getattr(first, "b64_json", None):
            raw = base64.b64decode(first.b64_json)
            output_path.write_bytes(raw)
            return
        if getattr(first, "url", None):
            async with httpx.AsyncClient(timeout=60.0) as client:
                fetched = await client.get(first.url)
                fetched.raise_for_status()
                output_path.write_bytes(fetched.content)
            return
        raise RuntimeError("provider returned neither b64_json nor url")

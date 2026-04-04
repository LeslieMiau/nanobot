"""Text-to-speech providers for voice output."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import httpx
from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import Config, TTSConfig


class TTSProvider(ABC):
    """Base class for text-to-speech providers."""

    @abstractmethod
    async def synthesize(self, text: str, voice: str = "alloy", model: str = "tts-1") -> bytes:
        """Convert text to speech audio (mp3 bytes)."""


class OpenAITTSProvider(TTSProvider):
    """TTS via OpenAI-compatible /v1/audio/speech endpoint."""

    def __init__(self, api_key: str, api_base: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")

    async def synthesize(self, text: str, voice: str = "alloy", model: str = "tts-1") -> bytes:
        url = f"{self.api_base}/audio/speech"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": model, "input": text, "voice": voice},
                timeout=60.0,
            )
            resp.raise_for_status()
            return resp.content


class GroqTTSProvider(TTSProvider):
    """TTS via Groq's OpenAI-compatible speech endpoint."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def synthesize(self, text: str, voice: str = "alloy", model: str = "playai-tts") -> bytes:
        url = "https://api.groq.com/openai/v1/audio/speech"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": model, "input": text, "voice": voice},
                timeout=60.0,
            )
            resp.raise_for_status()
            return resp.content


def get_tts_provider(tts_config: TTSConfig | None = None, root_config: Config | None = None) -> TTSProvider:
    """Create a TTS provider from configuration, with fallback to LLM provider keys."""
    provider_name = tts_config.provider if tts_config else "openai"
    api_key = (tts_config.api_key if tts_config else "") or ""

    # Fallback: resolve key from the matching LLM provider config
    if not api_key and root_config:
        if provider_name == "openai":
            api_key = root_config.providers.openai.api_key or os.environ.get("OPENAI_API_KEY", "")
        elif provider_name == "groq":
            api_key = root_config.providers.groq.api_key or os.environ.get("GROQ_API_KEY", "")

    if not api_key:
        raise ValueError(
            f"No API key for TTS provider '{provider_name}'. "
            "Set api.tts.apiKey in config or configure the matching LLM provider key."
        )

    if provider_name == "openai":
        api_base = (tts_config.api_base if tts_config and tts_config.api_base else "") or "https://api.openai.com/v1"
        return OpenAITTSProvider(api_key=api_key, api_base=api_base)
    elif provider_name == "groq":
        return GroqTTSProvider(api_key=api_key)
    else:
        raise ValueError(f"Unknown TTS provider: {provider_name}")

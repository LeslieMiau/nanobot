"""HomePod output-only channel — sends agent responses as spoken audio via AirPlay.

This channel does NOT handle inbound messages. Voice input comes through
Siri Shortcuts → HTTP API → AgentLoop. This channel provides the output
path: AgentLoop → TTS → AirPlay → HomePod speaker.

Requires: pip install 'nanobot-ai[homepod]'
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel


class HomePodChannel(BaseChannel):
    """Output-only channel that speaks agent responses through HomePod via AirPlay."""

    name = "homepod"
    display_name = "HomePod"

    def __init__(self, config: Any, bus: MessageBus):
        super().__init__(config, bus)
        cfg = config if isinstance(config, dict) else {}
        self._device_name: str = cfg.get("device_name", cfg.get("deviceName", ""))
        self._tts_provider_name: str = cfg.get("tts_provider", cfg.get("ttsProvider", "openai"))
        self._tts_voice: str = cfg.get("tts_voice", cfg.get("ttsVoice", "alloy"))
        self._tts_model: str = cfg.get("tts_model", cfg.get("ttsModel", "tts-1"))
        self._tts_api_key: str = cfg.get("tts_api_key", cfg.get("ttsApiKey", ""))
        self._tts_api_base: str = cfg.get("tts_api_base", cfg.get("ttsApiBase", ""))
        self._streamer = None
        self._tts = None

    async def start(self) -> None:
        """Initialize AirPlay streamer and discover HomePod devices."""
        try:
            from nanobot.audio.airplay import AirPlayStreamer
        except ImportError:
            logger.error(
                "HomePod channel requires pyatv. Install with: pip install 'nanobot-ai[homepod]'"
            )
            return

        self._streamer = AirPlayStreamer()
        devices = await self._streamer.scan()
        if not devices:
            logger.warning("HomePod channel: no AirPlay devices found on network")
        elif self._device_name:
            names = [d["name"] for d in devices]
            if self._device_name not in names:
                logger.warning(
                    "HomePod channel: configured device '{}' not found. Available: {}",
                    self._device_name, names,
                )
            else:
                logger.info("HomePod channel: connected to '{}'", self._device_name)
        else:
            # Auto-select first device
            self._device_name = devices[0]["name"]
            logger.info("HomePod channel: auto-selected '{}'", self._device_name)

        self._running = True
        logger.info("HomePod channel started (output-only, device='{}')", self._device_name)

    async def stop(self) -> None:
        """Stop the HomePod channel."""
        self._running = False
        self._streamer = None
        logger.info("HomePod channel stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Convert message to speech and stream to HomePod via AirPlay."""
        if not self._streamer or not self._device_name:
            logger.warning("HomePod channel: not ready (no streamer or device)")
            return

        text = msg.content
        if not text or not text.strip():
            return

        # Strip markdown for voice
        from nanobot.api.server import _strip_markdown
        plain_text = _strip_markdown(text)
        if not plain_text:
            return

        try:
            tts = await self._get_tts()
            audio_bytes = await tts.synthesize(
                plain_text, voice=self._tts_voice, model=self._tts_model
            )
            await self._streamer.stream_audio(self._device_name, audio_bytes)
            logger.debug("HomePod: spoke {} chars to '{}'", len(plain_text), self._device_name)
        except Exception as e:
            logger.error("HomePod channel send failed: {}", e)
            raise

    async def _get_tts(self):
        """Lazily initialize and return the TTS provider."""
        if self._tts is None:
            from nanobot.providers.tts import get_tts_provider
            from nanobot.config.schema import TTSConfig

            tts_config = TTSConfig(
                provider=self._tts_provider_name,
                api_key=self._tts_api_key,
                api_base=self._tts_api_base,
                voice=self._tts_voice,
                model=self._tts_model,
            )
            # Try to get root config for key fallback
            root_config = getattr(self, "_root_config", None)
            self._tts = get_tts_provider(tts_config, root_config)
        return self._tts

    def get_runtime_status(self) -> dict[str, Any]:
        return {
            "device": self._device_name,
            "tts_provider": self._tts_provider_name,
            "known_devices": self._streamer.known_devices if self._streamer else [],
        }

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return {
            "enabled": False,
            "deviceName": "",
            "ttsProvider": "openai",
            "ttsVoice": "alloy",
            "ttsModel": "tts-1",
            "allowFrom": ["*"],
        }

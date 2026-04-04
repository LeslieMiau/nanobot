"""AirPlay audio streaming to Apple devices (HomePod, Apple TV).

Requires the `pyatv` library: pip install 'nanobot-ai[homepod]'
"""

from __future__ import annotations

import asyncio
import io
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger


class AirPlayStreamer:
    """Discover and stream audio to AirPlay devices on the local network."""

    def __init__(self):
        self._devices: dict[str, Any] = {}  # name -> pyatv.interface.AppleTV
        self._scan_lock = asyncio.Lock()

    async def scan(self, timeout: float = 5.0) -> list[dict[str, str]]:
        """Scan for AirPlay devices on the local network.

        Returns list of {"name": ..., "identifier": ...} dicts.
        """
        try:
            import pyatv
        except ImportError:
            raise ImportError(
                "pyatv is required for AirPlay support. "
                "Install with: pip install 'nanobot-ai[homepod]'"
            )

        async with self._scan_lock:
            atvs = await pyatv.scan(asyncio.get_event_loop(), timeout=timeout)
            results = []
            for atv in atvs:
                results.append({
                    "name": atv.name,
                    "identifier": atv.identifier,
                })
                self._devices[atv.name] = atv
            logger.info("AirPlay scan found {} device(s): {}", len(results), [r["name"] for r in results])
            return results

    async def get_device(self, device_name: str) -> Any:
        """Get a scanned device config by name. Rescans if not found."""
        if device_name not in self._devices:
            await self.scan()
        conf = self._devices.get(device_name)
        if not conf:
            raise ValueError(
                f"AirPlay device '{device_name}' not found. "
                f"Available: {list(self._devices.keys())}"
            )
        return conf

    async def stream_audio(self, device_name: str, audio_data: bytes) -> None:
        """Stream audio bytes (mp3) to an AirPlay device.

        Args:
            device_name: Name of the target device (e.g. "Living Room HomePod").
            audio_data: MP3 audio bytes to play.
        """
        try:
            import pyatv
        except ImportError:
            raise ImportError("pyatv is required for AirPlay streaming.")

        conf = await self.get_device(device_name)

        atv = await pyatv.connect(conf, asyncio.get_event_loop())
        try:
            # pyatv stream_file requires a file path
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                tmp.write(audio_data)
                tmp_path = Path(tmp.name)

            try:
                await atv.stream.stream_file(str(tmp_path))
                logger.info("Streamed audio to '{}'", device_name)
            finally:
                tmp_path.unlink(missing_ok=True)
        finally:
            atv.close()

    @property
    def known_devices(self) -> list[str]:
        """Return names of devices found in the last scan."""
        return list(self._devices.keys())

"""Helpers for restart notification messages."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

RESTART_NOTIFY_CHANNEL_ENV = "NANOBOT_RESTART_NOTIFY_CHANNEL"
RESTART_NOTIFY_CHAT_ID_ENV = "NANOBOT_RESTART_NOTIFY_CHAT_ID"
RESTART_STARTED_AT_ENV = "NANOBOT_RESTART_STARTED_AT"
RESTART_MARKER_PATH = Path.home() / ".nanobot" / "restart_marker.json"
RESTART_COOLDOWN_S = 120  # minimum seconds between consecutive process restarts


@dataclass(frozen=True)
class RestartNotice:
    channel: str
    chat_id: str
    started_at_raw: str


@dataclass(frozen=True)
class RestartMarker:
    reason: str
    started_at_raw: str


def format_restart_completed_message(started_at_raw: str) -> str:
    """Build restart completion text and include elapsed time when available."""
    elapsed_suffix = ""
    if started_at_raw:
        try:
            elapsed_s = max(0.0, time.time() - float(started_at_raw))
            elapsed_suffix = f" in {elapsed_s:.1f}s"
        except ValueError:
            pass
    return f"Restart completed{elapsed_suffix}."


def set_restart_notice_to_env(*, channel: str, chat_id: str) -> None:
    """Write restart notice env values for the next process."""
    os.environ[RESTART_NOTIFY_CHANNEL_ENV] = channel
    os.environ[RESTART_NOTIFY_CHAT_ID_ENV] = chat_id
    os.environ[RESTART_STARTED_AT_ENV] = str(time.time())


def consume_restart_notice_from_env() -> RestartNotice | None:
    """Read and clear restart notice env values once for this process."""
    channel = os.environ.pop(RESTART_NOTIFY_CHANNEL_ENV, "").strip()
    chat_id = os.environ.pop(RESTART_NOTIFY_CHAT_ID_ENV, "").strip()
    started_at_raw = os.environ.pop(RESTART_STARTED_AT_ENV, "").strip()
    if not (channel and chat_id):
        return None
    return RestartNotice(channel=channel, chat_id=chat_id, started_at_raw=started_at_raw)


def should_show_cli_restart_notice(notice: RestartNotice, session_id: str) -> bool:
    """Return True when a restart notice should be shown in this CLI session."""
    if notice.channel != "cli":
        return False
    if ":" in session_id:
        _, cli_chat_id = session_id.split(":", 1)
    else:
        cli_chat_id = session_id
    return not notice.chat_id or notice.chat_id == cli_chat_id


def is_restart_in_cooldown(*, path: Path = RESTART_MARKER_PATH, cooldown_s: float = RESTART_COOLDOWN_S) -> bool:
    """Return True if the previous restart happened less than *cooldown_s* ago.

    Reads the marker without clearing it so the gateway can still consume
    the reason later via :func:`read_and_clear_restart_marker`.
    """
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        started_at = float(payload.get("started_at_raw", 0))
        return (time.time() - started_at) < cooldown_s
    except Exception:
        return False


def write_restart_marker(reason: str, *, path: Path = RESTART_MARKER_PATH) -> None:
    """Persist a restart marker so the next process can report recovery."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"reason": reason, "started_at_raw": str(time.time())}),
        encoding="utf-8",
    )


def read_and_clear_restart_marker(*, path: Path = RESTART_MARKER_PATH) -> RestartMarker | None:
    """Load and delete the restart marker once."""
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        reason = str(payload.get("reason", "")).strip() or "unknown"
        started_at_raw = str(payload.get("started_at_raw", "")).strip()
        return RestartMarker(reason=reason, started_at_raw=started_at_raw)
    except Exception:
        return None
    finally:
        path.unlink(missing_ok=True)

"""Telegram channel implementation using python-telegram-bot."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from pydantic import Field
from telegram import BotCommand, ReactionTypeEmoji, ReplyParameters, Update
from telegram.error import BadRequest, NetworkError, TimedOut
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.command.builtin import build_help_text
from nanobot.config.paths import get_media_dir
from nanobot.config.schema import Base
from nanobot.security.network import validate_url_target
from nanobot.utils.helpers import split_message

TELEGRAM_MAX_MESSAGE_LEN = 4000  # Telegram message character limit
TELEGRAM_REPLY_CONTEXT_MAX_LEN = TELEGRAM_MAX_MESSAGE_LEN  # Max length for reply context in user message


def _strip_md(s: str) -> str:
    """Strip markdown inline formatting from text."""
    s = re.sub(r'\*\*(.+?)\*\*', r'\1', s)
    s = re.sub(r'__(.+?)__', r'\1', s)
    s = re.sub(r'~~(.+?)~~', r'\1', s)
    s = re.sub(r'`([^`]+)`', r'\1', s)
    return s.strip()


def _render_table_box(table_lines: list[str]) -> str:
    """Convert markdown pipe-table to compact aligned text for <pre> display."""

    def dw(s: str) -> int:
        return sum(2 if unicodedata.east_asian_width(c) in ('W', 'F') else 1 for c in s)

    rows: list[list[str]] = []
    has_sep = False
    for line in table_lines:
        cells = [_strip_md(c) for c in line.strip().strip('|').split('|')]
        if all(re.match(r'^:?-+:?$', c) for c in cells if c):
            has_sep = True
            continue
        rows.append(cells)
    if not rows or not has_sep:
        return '\n'.join(table_lines)

    ncols = max(len(r) for r in rows)
    for r in rows:
        r.extend([''] * (ncols - len(r)))
    widths = [max(dw(r[c]) for r in rows) for c in range(ncols)]

    def dr(cells: list[str]) -> str:
        return '  '.join(f'{c}{" " * (w - dw(c))}' for c, w in zip(cells, widths))

    out = [dr(rows[0])]
    out.append('  '.join('─' * w for w in widths))
    for row in rows[1:]:
        out.append(dr(row))
    return '\n'.join(out)


def _markdown_to_telegram_html(text: str) -> str:
    """
    Convert markdown to Telegram-safe HTML.
    """
    if not text:
        return ""

    # 1. Extract and protect code blocks (preserve content from other processing)
    code_blocks: list[str] = []
    def save_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(1))
        return f"\x00CB{len(code_blocks) - 1}\x00"

    text = re.sub(r'```[\w]*\n?([\s\S]*?)```', save_code_block, text)

    # 1.5. Convert markdown tables to box-drawing (reuse code_block placeholders)
    lines = text.split('\n')
    rebuilt: list[str] = []
    li = 0
    while li < len(lines):
        if re.match(r'^\s*\|.+\|', lines[li]):
            tbl: list[str] = []
            while li < len(lines) and re.match(r'^\s*\|.+\|', lines[li]):
                tbl.append(lines[li])
                li += 1
            box = _render_table_box(tbl)
            if box != '\n'.join(tbl):
                code_blocks.append(box)
                rebuilt.append(f"\x00CB{len(code_blocks) - 1}\x00")
            else:
                rebuilt.extend(tbl)
        else:
            rebuilt.append(lines[li])
            li += 1
    text = '\n'.join(rebuilt)

    # 2. Extract and protect inline code
    inline_codes: list[str] = []
    def save_inline_code(m: re.Match) -> str:
        inline_codes.append(m.group(1))
        return f"\x00IC{len(inline_codes) - 1}\x00"

    text = re.sub(r'`([^`]+)`', save_inline_code, text)

    # 3. Headers # Title -> just the title text
    text = re.sub(r'^#{1,6}\s+(.+)$', r'\1', text, flags=re.MULTILINE)

    # 4. Blockquotes > text -> just the text (before HTML escaping)
    text = re.sub(r'^>\s*(.*)$', r'\1', text, flags=re.MULTILINE)

    # 5. Escape HTML special characters
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # 6. Links [text](url) - must be before bold/italic to handle nested cases
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # 7. Bold **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)

    # 8. Italic _text_ (avoid matching inside words like some_var_name)
    text = re.sub(r'(?<![a-zA-Z0-9])_([^_]+)_(?![a-zA-Z0-9])', r'<i>\1</i>', text)

    # 9. Strikethrough ~~text~~
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)

    # 10. Bullet lists - item -> • item
    text = re.sub(r'^[-*]\s+', '• ', text, flags=re.MULTILINE)

    # 11. Restore inline code with HTML tags
    for i, code in enumerate(inline_codes):
        # Escape HTML in code content
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00IC{i}\x00", f"<code>{escaped}</code>")

    # 12. Restore code blocks with HTML tags
    for i, code in enumerate(code_blocks):
        # Escape HTML in code content
        escaped = code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        text = text.replace(f"\x00CB{i}\x00", f"<pre><code>{escaped}</code></pre>")

    return text


_SEND_MAX_RETRIES = 3
_SEND_RETRY_BASE_DELAY = 0.5  # seconds, doubled each retry
_WATCHDOG_INTERVAL_S = 30
_WATCHDOG_ERROR_THRESHOLD = 3
_WATCHDOG_PROBE_TIMEOUT_S = 15.0
_WATCHDOG_RESTART_BACKOFF_S = 5.0
_WATCHDOG_MAX_CHANNEL_RESTARTS = 3


@dataclass
class _StreamBuf:
    """Per-chat streaming accumulator for progressive message editing."""
    text: str = ""
    message_id: int | None = None
    last_edit: float = 0.0
    stream_id: str | None = None


class TelegramConfig(Base):
    """Telegram channel configuration."""

    enabled: bool = False
    token: str = ""
    allow_from: list[str] = Field(default_factory=list)
    proxy: str | None = None
    use_env_proxy: bool = True
    reply_to_message: bool = False
    react_emoji: str = "👀"
    group_policy: Literal["open", "mention"] = "mention"
    connection_pool_size: int = 32
    pool_timeout: float = 5.0
    streaming: bool = True
    watchdog_interval_s: int = _WATCHDOG_INTERVAL_S
    watchdog_probe_timeout_s: float = _WATCHDOG_PROBE_TIMEOUT_S
    watchdog_error_threshold: int = Field(default=_WATCHDOG_ERROR_THRESHOLD, ge=1)
    watchdog_restart_backoff_s: float = Field(default=_WATCHDOG_RESTART_BACKOFF_S, ge=0.0)
    watchdog_max_channel_restarts: int = Field(default=_WATCHDOG_MAX_CHANNEL_RESTARTS, ge=1)
    watchdog_notify_admin: bool = True


class TelegramChannel(BaseChannel):
    """
    Telegram channel using long polling.

    Simple and reliable - no webhook/public IP needed.
    """

    name = "telegram"
    display_name = "Telegram"

    # Commands registered with Telegram's command menu
    BOT_COMMANDS = [
        BotCommand("start", "Start the bot"),
        BotCommand("new", "Start a new conversation"),
        BotCommand("coding", "Start or manage coding tasks"),
        BotCommand("stop", "Stop the current task"),
        BotCommand("model", "List or switch models"),
        BotCommand("restart", "Restart the bot"),
        BotCommand("status", "Show bot status"),
        BotCommand("dream", "Run Dream memory consolidation now"),
        BotCommand("dream_log", "Show the latest Dream memory change"),
        BotCommand("dream_restore", "Restore Dream memory to an earlier version"),
        BotCommand("help", "Show available commands"),
    ]

    @classmethod
    def default_config(cls) -> dict[str, Any]:
        return TelegramConfig().model_dump(by_alias=True)

    _STREAM_EDIT_INTERVAL = 0.6  # min seconds between edit_message_text calls

    def __init__(self, config: Any, bus: MessageBus):
        if isinstance(config, dict):
            config = TelegramConfig.model_validate(config)
        super().__init__(config, bus)
        self.config: TelegramConfig = config
        self._app: Application | None = None
        self._chat_ids: dict[str, int] = {}  # Map sender_id to chat_id for replies
        self._typing_tasks: dict[str, asyncio.Task] = {}  # chat_id -> typing loop task
        self._media_group_buffers: dict[str, dict] = {}
        self._media_group_tasks: dict[str, asyncio.Task] = {}
        self._message_threads: dict[tuple[str, int], int] = {}
        self._bot_user_id: int | None = None
        self._bot_username: str | None = None
        self._stream_bufs: dict[str, _StreamBuf] = {}  # chat_id -> streaming state
        self._watchdog_task: asyncio.Task | None = None
        self._restart_lock = asyncio.Lock()
        self._probe_failures = 0
        self._watchdog_restart_failures = 0
        self._runtime_status = self._new_runtime_status()
        self._runtime_status["effective_proxy"] = self._resolve_proxy_settings()[2]
        self._runtime_status["runtime_source"] = str(Path(__file__).resolve().parents[2])

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def _new_runtime_status(self) -> dict[str, Any]:
        return {
            "effective_proxy": "unknown",
            "reconnect_count": 0,
            "last_inbound_at": None,
            "last_outbound_at": None,
            "last_probe_at": None,
            "last_probe_ok_at": None,
            "last_channel_restart_at": None,
            "last_poll_error_at": None,
            "last_send_error_at": None,
            "consecutive_poll_errors": 0,
            "consecutive_send_errors": 0,
            "polling_task_alive": False,
            "channel_restart_count": 0,
            "watchdog_restart_failures": 0,
            "last_error_summary": None,
            "runtime_source": "unknown",
            "running": False,
        }

    def _resolve_proxy_settings(self) -> tuple[str | None, bool, str]:
        explicit_proxy = (self.config.proxy or "").strip() or None
        if explicit_proxy:
            return explicit_proxy, False, f"explicit:{explicit_proxy}"
        if not self.config.use_env_proxy:
            return None, False, "direct"

        env_proxy = (
            os.environ.get("HTTPS_PROXY")
            or os.environ.get("HTTP_PROXY")
            or os.environ.get("ALL_PROXY")
            or os.environ.get("https_proxy")
            or os.environ.get("http_proxy")
            or os.environ.get("all_proxy")
        )
        if env_proxy:
            return None, True, f"env:{env_proxy}"
        return None, True, "env"

    def _set_last_error_summary(self, source: str, exc: Exception | str) -> None:
        if isinstance(exc, Exception):
            summary = f"{source}: {type(exc).__name__}: {exc}"
        else:
            summary = f"{source}: {exc}"
        self._runtime_status["last_error_summary"] = summary[:240]

    def _record_poll_error(self, exc: Exception | str) -> None:
        self._runtime_status["last_poll_error_at"] = self._now_iso()
        self._runtime_status["consecutive_poll_errors"] += 1
        self._set_last_error_summary("poll", exc)

    def _record_send_error(self, exc: Exception | str) -> None:
        self._runtime_status["last_send_error_at"] = self._now_iso()
        self._runtime_status["consecutive_send_errors"] += 1
        self._set_last_error_summary("send", exc)

    def _record_inbound_success(self) -> None:
        self._runtime_status["last_inbound_at"] = self._now_iso()

    def _record_outbound_success(self) -> None:
        self._runtime_status["last_outbound_at"] = self._now_iso()
        self._runtime_status["consecutive_send_errors"] = 0

    def _clear_poll_errors(self) -> None:
        self._runtime_status["consecutive_poll_errors"] = 0

    def _clear_send_errors(self) -> None:
        self._runtime_status["consecutive_send_errors"] = 0

    def get_runtime_status(self) -> dict[str, Any]:
        status = dict(self._runtime_status)
        status["polling_task_alive"] = self._is_polling_task_alive()
        status["probe_failures"] = self._probe_failures
        return status

    def _get_polling_task(self) -> asyncio.Task | None:
        # NOTE: Accesses private python-telegram-bot internals.  The attribute
        # name may change across library versions (_polling_task or the
        # name-mangled _Updater__polling_task).  Pin the PTB version and
        # re-check after upgrades.
        updater = getattr(self._app, "updater", None)
        if updater is None:
            return None
        task = getattr(updater, "_polling_task", None)
        if task is None:
            task = getattr(updater, "_Updater__polling_task", None)
        return task

    def _is_polling_task_alive(self) -> bool:
        task = self._get_polling_task()
        alive = bool(task) and not task.done()
        self._runtime_status["polling_task_alive"] = alive
        return alive

    def _build_application(self) -> Application:
        proxy, trust_env, effective_proxy = self._resolve_proxy_settings()
        self._runtime_status["effective_proxy"] = effective_proxy

        # Separate pools so long-polling (getUpdates) never starves outbound sends.
        api_request = HTTPXRequest(
            connection_pool_size=self.config.connection_pool_size,
            pool_timeout=self.config.pool_timeout,
            connect_timeout=30.0,
            read_timeout=30.0,
            proxy=proxy,
            httpx_kwargs={"trust_env": trust_env},
        )
        poll_request = HTTPXRequest(
            connection_pool_size=4,
            pool_timeout=self.config.pool_timeout,
            connect_timeout=30.0,
            read_timeout=30.0,
            proxy=proxy,
            httpx_kwargs={"trust_env": trust_env},
        )
        app = (
            Application.builder()
            .token(self.config.token)
            .request(api_request)
            .get_updates_request(poll_request)
            .build()
        )
        app.add_error_handler(self._on_error)
        app.add_handler(CommandHandler("start", self._on_start))
        app.add_handler(CommandHandler("new", self._forward_command))
        app.add_handler(CommandHandler("coding", self._forward_command))
        app.add_handler(CommandHandler("stop", self._forward_command))
        app.add_handler(CommandHandler("restart", self._forward_command))
        app.add_handler(CommandHandler("model", self._forward_command))
        app.add_handler(CommandHandler("status", self._forward_command))
        app.add_handler(CommandHandler("dream", self._forward_command))
        app.add_handler(
            MessageHandler(
                filters.Regex(r"^/(dream-log|dream_log|dream-restore|dream_restore)(?:@\w+)?(?:\s+.*)?$"),
                self._forward_command,
            )
        )
        app.add_handler(CommandHandler("help", self._on_help))
        app.add_handler(
            MessageHandler(
                (filters.TEXT | filters.PHOTO | filters.VOICE | filters.AUDIO | filters.Document.ALL)
                & ~filters.COMMAND,
                self._on_message,
            )
        )
        return app

    async def _start_application(self) -> None:
        if not self._app:
            raise RuntimeError("Telegram application is not built")

        logger.info("Starting Telegram bot (polling mode)...")
        await self._app.initialize()
        await self._app.start()

        bot_info = await self._app.bot.get_me()
        self._bot_user_id = getattr(bot_info, "id", None)
        self._bot_username = getattr(bot_info, "username", None)
        logger.info("Telegram bot @{} connected", bot_info.username)

        try:
            await self._app.bot.set_my_commands(self.BOT_COMMANDS)
            logger.debug("Telegram bot commands registered")
        except Exception as e:
            logger.warning("Failed to register bot commands: {}", e)

        await self._app.updater.start_polling(
            allowed_updates=["message"],
            drop_pending_updates=True,
            error_callback=self._on_polling_error,
        )
        self._clear_poll_errors()
        self._clear_send_errors()
        self._probe_failures = 0
        self._runtime_status["running"] = True
        self._runtime_status["polling_task_alive"] = self._is_polling_task_alive()

    async def _stop_application(self) -> None:
        app = self._app
        if not app:
            return

        logger.info("Stopping Telegram bot...")
        updater = getattr(app, "updater", None)
        if updater and getattr(updater, "running", False):
            with contextlib.suppress(RuntimeError):
                await updater.stop()
        if getattr(app, "running", False):
            with contextlib.suppress(RuntimeError):
                await app.stop()
        if getattr(app, "_initialized", False):
            with contextlib.suppress(RuntimeError):
                await app.shutdown()
        self._app = None
        self._bot_user_id = None
        self._bot_username = None
        self._runtime_status["polling_task_alive"] = False
        self._runtime_status["running"] = False

    async def _probe_connectivity(self) -> bool:
        if not self._app:
            return False
        self._runtime_status["last_probe_at"] = self._now_iso()
        try:
            await asyncio.wait_for(
                self._app.bot.get_me(),
                timeout=self.config.watchdog_probe_timeout_s,
            )
            self._runtime_status["last_probe_ok_at"] = self._runtime_status["last_probe_at"]
            return True
        except Exception as exc:
            self._set_last_error_summary("probe", exc)
            return False

    async def _restart_application(self, reason: str) -> None:
        if not self._running:
            return
        logger.warning("Restarting Telegram application due to {}", reason)
        self._runtime_status["channel_restart_count"] += 1
        self._runtime_status["last_channel_restart_at"] = self._now_iso()
        await self._stop_application()
        self._app = self._build_application()
        try:
            await self._start_application()
        except Exception:
            await self._stop_application()
            raise
        self._runtime_status["reconnect_count"] += 1
        self._runtime_status["consecutive_poll_errors"] = 0
        self._runtime_status["consecutive_send_errors"] = 0
        self._runtime_status["last_error_summary"] = None
        self._watchdog_restart_failures = 0
        self._runtime_status["watchdog_restart_failures"] = 0
        self._probe_failures = 0

    async def _request_process_restart(self, reason: str) -> None:
        callback = self.restart_callback
        if callback is None:
            logger.error("Telegram requested process restart without a restart callback: {}", reason)
            logger.error("No restart callback available; forcing exit so supervisor can restart the process")
            os._exit(1)
        result = callback(reason)
        if inspect.isawaitable(result):
            await result

    async def _escalate_process_restart(self, reason: str) -> None:
        self._set_last_error_summary("watchdog", reason)
        logger.error("Telegram watchdog exhausted channel self-heal; escalating to process restart")
        await self._request_process_restart(reason)

    async def _recover_if_needed(self, reason: str, *, probe_before_restart: bool = True) -> None:
        threshold_map = {
            "poll": "consecutive_poll_errors",
            "send": "consecutive_send_errors",
        }
        threshold_key = threshold_map.get(reason)
        if threshold_key and self._runtime_status[threshold_key] < self.config.watchdog_error_threshold:
            return
        if reason == "probe" and self._probe_failures < self.config.watchdog_error_threshold:
            return
        if not self._running:
            return

        async with self._restart_lock:
            if not self._running:
                return
            if threshold_key and self._runtime_status[threshold_key] < self.config.watchdog_error_threshold:
                return
            if reason == "probe" and self._probe_failures < self.config.watchdog_error_threshold:
                return

            if probe_before_restart and await self._probe_connectivity():
                self._probe_failures = 0
                if threshold_key == "consecutive_poll_errors":
                    self._clear_poll_errors()
                elif threshold_key == "consecutive_send_errors":
                    self._clear_send_errors()
                return

            delay = self.config.watchdog_restart_backoff_s * max(1, self._watchdog_restart_failures + 1)
            logger.warning("Telegram watchdog restarting channel due to {} in {:.1f}s", reason, delay)
            if delay > 0:
                await asyncio.sleep(delay)
            if not self._running:
                return
            restart_reason = {
                "poll": "poll-watchdog",
                "send": "send-watchdog",
                "probe": "probe-watchdog",
                "app-not-running": "app-not-running",
                "updater-not-running": "updater-not-running",
                "polling-task-dead": "polling-task-dead",
            }.get(reason, reason)
            try:
                await self._restart_application(restart_reason)
            except Exception as exc:
                self._watchdog_restart_failures += 1
                self._runtime_status["watchdog_restart_failures"] = self._watchdog_restart_failures
                self._record_poll_error(exc)
                logger.warning("Telegram watchdog reconnect failed: {}", exc)
                if self._watchdog_restart_failures >= self.config.watchdog_max_channel_restarts:
                    await self._escalate_process_restart("telegram self-heal exhausted")

    async def _watchdog_loop(self) -> None:
        try:
            while self._running:
                await asyncio.sleep(self.config.watchdog_interval_s)
                if not self._running:
                    return
                if not self._app or not getattr(self._app, "running", False):
                    await self._recover_if_needed("app-not-running", probe_before_restart=False)
                    continue
                updater = getattr(self._app, "updater", None)
                if updater is None or not getattr(updater, "running", False):
                    await self._recover_if_needed("updater-not-running", probe_before_restart=False)
                    continue
                if not self._is_polling_task_alive():
                    await self._recover_if_needed("polling-task-dead", probe_before_restart=False)
                    continue
                if self._runtime_status["consecutive_poll_errors"] >= self.config.watchdog_error_threshold:
                    await self._recover_if_needed("poll")
                    continue
                if self._runtime_status["consecutive_send_errors"] >= self.config.watchdog_error_threshold:
                    await self._recover_if_needed("send")
                    continue
                if await self._probe_connectivity():
                    self._probe_failures = 0
                else:
                    self._probe_failures += 1
                    await self._recover_if_needed("probe", probe_before_restart=False)
        except asyncio.CancelledError:
            pass

    def is_allowed(self, sender_id: str) -> bool:
        """Preserve Telegram's legacy id|username allowlist matching."""
        if super().is_allowed(sender_id):
            return True

        allow_list = getattr(self.config, "allow_from", [])
        if not allow_list or "*" in allow_list:
            return False

        sender_str = str(sender_id)
        if sender_str.count("|") != 1:
            return False

        sid, username = sender_str.split("|", 1)
        if not sid.isdigit() or not username:
            return False

        return sid in allow_list or username in allow_list

    @staticmethod
    def _normalize_telegram_command(content: str) -> str:
        """Map Telegram-safe command aliases back to canonical nanobot commands."""
        if not content.startswith("/"):
            return content
        if content == "/dream_log" or content.startswith("/dream_log "):
            return content.replace("/dream_log", "/dream-log", 1)
        if content == "/dream_restore" or content.startswith("/dream_restore "):
            return content.replace("/dream_restore", "/dream-restore", 1)
        return content

    async def start(self) -> None:
        """Start the Telegram bot with long polling."""
        if not self.config.token:
            logger.error("Telegram bot token not configured")
            return

        self._running = True
        self._runtime_status["running"] = True
        try:
            self._app = self._build_application()
            await self._start_application()
            if not self._watchdog_task or self._watchdog_task.done():
                self._watchdog_task = asyncio.create_task(self._watchdog_loop())
            while self._running:
                await asyncio.sleep(1)
        except Exception:
            self._running = False
            self._runtime_status["running"] = False
            await self._stop_application()
            raise
        finally:
            self._runtime_status["running"] = False

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        self._running = False
        self._runtime_status["running"] = False

        # Cancel all typing indicators
        for chat_id in list(self._typing_tasks):
            self._stop_typing(chat_id)

        for task in self._media_group_tasks.values():
            task.cancel()
        self._media_group_tasks.clear()
        self._media_group_buffers.clear()
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._watchdog_task
        self._watchdog_task = None
        await self._stop_application()

    @staticmethod
    def _get_media_type(path: str) -> str:
        """Guess media type from file extension."""
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext in ("jpg", "jpeg", "png", "gif", "webp"):
            return "photo"
        if ext == "ogg":
            return "voice"
        if ext in ("mp3", "m4a", "wav", "aac"):
            return "audio"
        return "document"

    @staticmethod
    def _is_remote_media_url(path: str) -> bool:
        return path.startswith(("http://", "https://"))

    async def send(self, msg: OutboundMessage) -> None:
        """Send a message through Telegram."""
        if not self._app:
            logger.warning("Telegram bot not running")
            self._record_send_error("Telegram bot not running")
            raise RuntimeError("Telegram bot not running")

        # Only stop typing indicator and remove reaction for final responses
        if not msg.metadata.get("_progress", False):
            self._stop_typing(msg.chat_id)
            if reply_to_message_id := msg.metadata.get("message_id"):
                try:
                    await self._remove_reaction(msg.chat_id, int(reply_to_message_id))
                except ValueError:
                    pass

        try:
            chat_id = int(msg.chat_id)
        except ValueError:
            logger.error("Invalid chat_id: {}", msg.chat_id)
            self._record_send_error(f"Invalid chat_id: {msg.chat_id}")
            raise
        reply_to_message_id = msg.metadata.get("message_id")
        message_thread_id = msg.metadata.get("message_thread_id")
        if message_thread_id is None and reply_to_message_id is not None:
            message_thread_id = self._message_threads.get((msg.chat_id, reply_to_message_id))
        thread_kwargs = {}
        if message_thread_id is not None:
            thread_kwargs["message_thread_id"] = message_thread_id

        reply_params = None
        if self.config.reply_to_message:
            if reply_to_message_id:
                reply_params = ReplyParameters(
                    message_id=reply_to_message_id,
                    allow_sending_without_reply=True
                )

        try:
            # Send media files
            for media_path in (msg.media or []):
                try:
                    media_type = self._get_media_type(media_path)
                    sender = {
                        "photo": self._app.bot.send_photo,
                        "voice": self._app.bot.send_voice,
                        "audio": self._app.bot.send_audio,
                    }.get(media_type, self._app.bot.send_document)
                    param = "photo" if media_type == "photo" else media_type if media_type in ("voice", "audio") else "document"

                    # Telegram Bot API accepts HTTP(S) URLs directly for media params.
                    if self._is_remote_media_url(media_path):
                        ok, error = validate_url_target(media_path)
                        if not ok:
                            raise ValueError(f"unsafe media URL: {error}")
                        await self._call_with_retry(
                            sender,
                            chat_id=chat_id,
                            **{param: media_path},
                            reply_parameters=reply_params,
                            **thread_kwargs,
                        )
                        continue

                    with open(media_path, "rb") as f:
                        await sender(
                            chat_id=chat_id,
                            **{param: f},
                            reply_parameters=reply_params,
                            **thread_kwargs,
                        )
                except Exception as e:
                    filename = media_path.rsplit("/", 1)[-1]
                    logger.error("Failed to send media {}: {}", media_path, e)
                    await self._app.bot.send_message(
                        chat_id=chat_id,
                        text=f"[Failed to send: {filename}]",
                        reply_parameters=reply_params,
                        **thread_kwargs,
                    )

            # Send text content
            if msg.content and msg.content != "[empty message]":
                for chunk in split_message(msg.content, TELEGRAM_MAX_MESSAGE_LEN):
                    await self._send_text(chat_id, chunk, reply_params, thread_kwargs)
        except Exception as exc:
            self._record_send_error(exc)
            raise

        self._record_outbound_success()

    async def _call_with_retry(self, fn, *args, **kwargs):
        """Call an async Telegram API function with retry on pool/network timeout and RetryAfter."""
        from telegram.error import RetryAfter
        
        for attempt in range(1, _SEND_MAX_RETRIES + 1):
            try:
                return await fn(*args, **kwargs)
            except TimedOut:
                if attempt == _SEND_MAX_RETRIES:
                    raise
                delay = _SEND_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "Telegram timeout (attempt {}/{}), retrying in {:.1f}s",
                    attempt, _SEND_MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)
            except RetryAfter as e:
                if attempt == _SEND_MAX_RETRIES:
                    raise
                delay = float(e.retry_after)
                logger.warning(
                    "Telegram Flood Control (attempt {}/{}), retrying in {:.1f}s",
                    attempt, _SEND_MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)

    async def _send_text(
        self,
        chat_id: int,
        text: str,
        reply_params=None,
        thread_kwargs: dict | None = None,
    ) -> None:
        """Send a plain text message with HTML fallback."""
        try:
            html = _markdown_to_telegram_html(text)
            await self._call_with_retry(
                self._app.bot.send_message,
                chat_id=chat_id, text=html, parse_mode="HTML",
                reply_parameters=reply_params,
                **(thread_kwargs or {}),
            )
        except Exception as e:
            logger.warning("HTML parse failed, falling back to plain text: {}", e)
            try:
                await self._call_with_retry(
                    self._app.bot.send_message,
                    chat_id=chat_id,
                    text=text,
                    reply_parameters=reply_params,
                    **(thread_kwargs or {}),
                )
            except Exception as e2:
                logger.error("Error sending Telegram message: {}", e2)
                raise

    @staticmethod
    def _is_not_modified_error(exc: Exception) -> bool:
        return isinstance(exc, BadRequest) and "message is not modified" in str(exc).lower()

    async def send_delta(self, chat_id: str, delta: str, metadata: dict[str, Any] | None = None) -> None:
        """Progressive message editing: send on first delta, edit on subsequent ones."""
        if not self._app:
            self._record_send_error("Telegram bot not running")
            raise RuntimeError("Telegram bot not running")
        meta = metadata or {}
        int_chat_id = int(chat_id)
        stream_id = meta.get("_stream_id")

        if meta.get("_stream_end"):
            buf = self._stream_bufs.get(chat_id)
            if not buf or not buf.message_id or not buf.text:
                return
            if stream_id is not None and buf.stream_id is not None and buf.stream_id != stream_id:
                return
            self._stop_typing(chat_id)
            if reply_to_message_id := meta.get("message_id"):
                try:
                    await self._remove_reaction(chat_id, int(reply_to_message_id))
                except ValueError:
                    pass
            try:
                html = _markdown_to_telegram_html(buf.text)
                await self._call_with_retry(
                    self._app.bot.edit_message_text,
                    chat_id=int_chat_id, message_id=buf.message_id,
                    text=html, parse_mode="HTML",
                )
            except Exception as e:
                if self._is_not_modified_error(e):
                    logger.debug("Final stream edit already applied for {}", chat_id)
                    self._stream_bufs.pop(chat_id, None)
                    self._record_outbound_success()
                    return
                logger.debug("Final stream edit failed (HTML), trying plain: {}", e)
                try:
                    await self._call_with_retry(
                        self._app.bot.edit_message_text,
                        chat_id=int_chat_id, message_id=buf.message_id,
                        text=buf.text,
                    )
                except Exception as e2:
                    if self._is_not_modified_error(e2):
                        logger.debug("Final stream plain edit already applied for {}", chat_id)
                        self._stream_bufs.pop(chat_id, None)
                        self._record_outbound_success()
                        return
                    logger.warning("Final stream edit failed: {}", e2)
                    self._record_send_error(e2)
                    raise  # Let ChannelManager handle retry
            self._stream_bufs.pop(chat_id, None)
            self._record_outbound_success()
            return

        buf = self._stream_bufs.get(chat_id)
        if buf is None or (stream_id is not None and buf.stream_id is not None and buf.stream_id != stream_id):
            buf = _StreamBuf(stream_id=stream_id)
            self._stream_bufs[chat_id] = buf
        elif buf.stream_id is None:
            buf.stream_id = stream_id
        buf.text += delta

        if not buf.text.strip():
            return

        now = time.monotonic()
        if buf.message_id is None:
            try:
                sent = await self._call_with_retry(
                    self._app.bot.send_message,
                    chat_id=int_chat_id, text=buf.text,
                )
                buf.message_id = sent.message_id
                buf.last_edit = now
                self._record_outbound_success()
            except Exception as e:
                logger.warning("Stream initial send failed: {}", e)
                self._record_send_error(e)
                raise  # Let ChannelManager handle retry
        elif (now - buf.last_edit) >= self._STREAM_EDIT_INTERVAL:
            try:
                await self._call_with_retry(
                    self._app.bot.edit_message_text,
                    chat_id=int_chat_id, message_id=buf.message_id,
                    text=buf.text,
                )
                buf.last_edit = now
                self._record_outbound_success()
            except Exception as e:
                if self._is_not_modified_error(e):
                    buf.last_edit = now
                    return
                logger.warning("Stream edit failed: {}", e)
                self._record_send_error(e)
                raise  # Let ChannelManager handle retry

    async def _on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not update.message or not update.effective_user:
            return

        user = update.effective_user
        await update.message.reply_text(
            f"👋 Hi {user.first_name}! I'm nanobot.\n\n"
            "Send me a message and I'll respond!\n"
            "Type /help to see available commands."
        )

    async def _on_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command, bypassing ACL so all users can access it."""
        if not update.message:
            return
        await update.message.reply_text(build_help_text())

    @staticmethod
    def _sender_id(user) -> str:
        """Build sender_id with username for allowlist matching."""
        sid = str(user.id)
        return f"{sid}|{user.username}" if user.username else sid

    @staticmethod
    def _derive_topic_session_key(message) -> str | None:
        """Derive topic-scoped session key for non-private Telegram chats."""
        message_thread_id = getattr(message, "message_thread_id", None)
        if message.chat.type == "private" or message_thread_id is None:
            return None
        return f"telegram:{message.chat_id}:topic:{message_thread_id}"

    @staticmethod
    def _build_message_metadata(message, user) -> dict:
        """Build common Telegram inbound metadata payload."""
        reply_to = getattr(message, "reply_to_message", None)
        return {
            "message_id": message.message_id,
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "is_group": message.chat.type != "private",
            "message_thread_id": getattr(message, "message_thread_id", None),
            "is_forum": bool(getattr(message.chat, "is_forum", False)),
            "reply_to_message_id": getattr(reply_to, "message_id", None) if reply_to else None,
        }

    async def _extract_reply_context(self, message) -> str | None:
        """Extract text from the message being replied to, if any."""
        reply = getattr(message, "reply_to_message", None)
        if not reply:
            return None
        text = getattr(reply, "text", None) or getattr(reply, "caption", None) or ""
        if len(text) > TELEGRAM_REPLY_CONTEXT_MAX_LEN:
            text = text[:TELEGRAM_REPLY_CONTEXT_MAX_LEN] + "..."
            
        if not text:
            return None
            
        bot_id, _ = await self._ensure_bot_identity()
        reply_user = getattr(reply, "from_user", None)
        
        if bot_id and reply_user and getattr(reply_user, "id", None) == bot_id:
            return f"[Reply to bot: {text}]"
        elif reply_user and getattr(reply_user, "username", None):
            return f"[Reply to @{reply_user.username}: {text}]"
        elif reply_user and getattr(reply_user, "first_name", None):
            return f"[Reply to {reply_user.first_name}: {text}]"
        else:
            return f"[Reply to: {text}]"

    async def _download_message_media(
        self, msg, *, add_failure_content: bool = False
    ) -> tuple[list[str], list[str]]:
        """Download media from a message (current or reply). Returns (media_paths, content_parts)."""
        media_file = None
        media_type = None
        if getattr(msg, "photo", None):
            media_file = msg.photo[-1]
            media_type = "image"
        elif getattr(msg, "voice", None):
            media_file = msg.voice
            media_type = "voice"
        elif getattr(msg, "audio", None):
            media_file = msg.audio
            media_type = "audio"
        elif getattr(msg, "document", None):
            media_file = msg.document
            media_type = "file"
        elif getattr(msg, "video", None):
            media_file = msg.video
            media_type = "video"
        elif getattr(msg, "video_note", None):
            media_file = msg.video_note
            media_type = "video"
        elif getattr(msg, "animation", None):
            media_file = msg.animation
            media_type = "animation"
        if not media_file or not self._app:
            return [], []
        try:
            file = await self._app.bot.get_file(media_file.file_id)
            ext = self._get_extension(
                media_type,
                getattr(media_file, "mime_type", None),
                getattr(media_file, "file_name", None),
            )
            media_dir = get_media_dir("telegram")
            unique_id = getattr(media_file, "file_unique_id", media_file.file_id)
            file_path = media_dir / f"{unique_id}{ext}"
            await file.download_to_drive(str(file_path))
            path_str = str(file_path)
            if media_type in ("voice", "audio"):
                transcription = await self.transcribe_audio(file_path)
                if transcription:
                    logger.info("Transcribed {}: {}...", media_type, transcription[:50])
                    return [path_str], [f"[transcription: {transcription}]"]
                return [path_str], [f"[{media_type}: {path_str}]"]
            return [path_str], [f"[{media_type}: {path_str}]"]
        except Exception as e:
            logger.warning("Failed to download message media: {}", e)
            if add_failure_content:
                return [], [f"[{media_type}: download failed]"]
            return [], []

    async def _ensure_bot_identity(self) -> tuple[int | None, str | None]:
        """Load bot identity once and reuse it for mention/reply checks."""
        if self._bot_user_id is not None or self._bot_username is not None:
            return self._bot_user_id, self._bot_username
        if not self._app:
            return None, None
        bot_info = await self._app.bot.get_me()
        self._bot_user_id = getattr(bot_info, "id", None)
        self._bot_username = getattr(bot_info, "username", None)
        return self._bot_user_id, self._bot_username

    @staticmethod
    def _has_mention_entity(
        text: str,
        entities,
        bot_username: str,
        bot_id: int | None,
    ) -> bool:
        """Check Telegram mention entities against the bot username."""
        handle = f"@{bot_username}".lower()
        for entity in entities or []:
            entity_type = getattr(entity, "type", None)
            if entity_type == "text_mention":
                user = getattr(entity, "user", None)
                if user is not None and bot_id is not None and getattr(user, "id", None) == bot_id:
                    return True
                continue
            if entity_type != "mention":
                continue
            offset = getattr(entity, "offset", None)
            length = getattr(entity, "length", None)
            if offset is None or length is None:
                continue
            if text[offset : offset + length].lower() == handle:
                return True
        return handle in text.lower()

    async def _is_group_message_for_bot(self, message) -> bool:
        """Allow group messages when policy is open, @mentioned, or replying to the bot."""
        if message.chat.type == "private" or self.config.group_policy == "open":
            return True

        bot_id, bot_username = await self._ensure_bot_identity()
        if bot_username:
            text = message.text or ""
            caption = message.caption or ""
            if self._has_mention_entity(
                text,
                getattr(message, "entities", None),
                bot_username,
                bot_id,
            ):
                return True
            if self._has_mention_entity(
                caption,
                getattr(message, "caption_entities", None),
                bot_username,
                bot_id,
            ):
                return True

        reply_user = getattr(getattr(message, "reply_to_message", None), "from_user", None)
        return bool(bot_id and reply_user and reply_user.id == bot_id)

    def _remember_thread_context(self, message) -> None:
        """Cache topic thread id by chat/message id for follow-up replies."""
        message_thread_id = getattr(message, "message_thread_id", None)
        if message_thread_id is None:
            return
        key = (str(message.chat_id), message.message_id)
        self._message_threads[key] = message_thread_id
        if len(self._message_threads) > 1000:
            self._message_threads.pop(next(iter(self._message_threads)))

    async def _forward_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Forward slash commands to the bus for unified handling in AgentLoop."""
        if not update.message or not update.effective_user:
            return
        message = update.message
        user = update.effective_user
        self._remember_thread_context(message)
        content = message.text or ""
        if content.startswith("/") and "@" in content:
            cmd_part, *rest = content.split(" ", 1)
            cmd_part = cmd_part.split("@")[0]
            content = f"{cmd_part} {rest[0]}" if rest else cmd_part
        content = self._normalize_telegram_command(content)
        if await self._handle_message(
            sender_id=self._sender_id(user),
            chat_id=str(message.chat_id),
            content=content,
            metadata=self._build_message_metadata(message, user),
            session_key=self._derive_topic_session_key(message),
        ):
            self._record_inbound_success()

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming messages (text, photos, voice, documents)."""
        if not update.message or not update.effective_user:
            return

        message = update.message
        user = update.effective_user
        chat_id = message.chat_id
        sender_id = self._sender_id(user)
        self._remember_thread_context(message)

        # Store chat_id for replies
        self._chat_ids[sender_id] = chat_id

        if not await self._is_group_message_for_bot(message):
            return

        # Build content from text and/or media
        content_parts = []
        media_paths = []

        # Text content
        if message.text:
            content_parts.append(message.text)
        if message.caption:
            content_parts.append(message.caption)

        # Download current message media
        current_media_paths, current_media_parts = await self._download_message_media(
            message, add_failure_content=True
        )
        media_paths.extend(current_media_paths)
        content_parts.extend(current_media_parts)
        if current_media_paths:
            logger.debug("Downloaded message media to {}", current_media_paths[0])

        # Reply context: text and/or media from the replied-to message
        reply = getattr(message, "reply_to_message", None)
        if reply is not None:
            reply_ctx = await self._extract_reply_context(message)
            reply_media, reply_media_parts = await self._download_message_media(reply)
            if reply_media:
                media_paths = reply_media + media_paths
                logger.debug("Attached replied-to media: {}", reply_media[0])
            tag = reply_ctx or (f"[Reply to: {reply_media_parts[0]}]" if reply_media_parts else None)
            if tag:
                content_parts.insert(0, tag)
        content = "\n".join(content_parts) if content_parts else "[empty message]"

        logger.debug("Telegram message from {}: {}...", sender_id, content[:50])

        str_chat_id = str(chat_id)
        metadata = self._build_message_metadata(message, user)
        session_key = self._derive_topic_session_key(message)

        # Telegram media groups: buffer briefly, forward as one aggregated turn.
        if media_group_id := getattr(message, "media_group_id", None):
            key = f"{str_chat_id}:{media_group_id}"
            if key not in self._media_group_buffers:
                self._media_group_buffers[key] = {
                    "sender_id": sender_id, "chat_id": str_chat_id,
                    "contents": [], "media": [],
                    "metadata": metadata,
                    "session_key": session_key,
                }
                self._start_typing(str_chat_id)
                await self._add_reaction(str_chat_id, message.message_id, self.config.react_emoji)
            buf = self._media_group_buffers[key]
            if content and content != "[empty message]":
                buf["contents"].append(content)
            buf["media"].extend(media_paths)
            if key not in self._media_group_tasks:
                self._media_group_tasks[key] = asyncio.create_task(self._flush_media_group(key))
            return

        # Start typing indicator before processing
        self._start_typing(str_chat_id)
        await self._add_reaction(str_chat_id, message.message_id, self.config.react_emoji)

        # Forward to the message bus
        if await self._handle_message(
            sender_id=sender_id,
            chat_id=str_chat_id,
            content=content,
            media=media_paths,
            metadata=metadata,
            session_key=session_key,
        ):
            self._record_inbound_success()

    async def _flush_media_group(self, key: str) -> None:
        """Wait briefly, then forward buffered media-group as one turn."""
        try:
            await asyncio.sleep(0.6)
            if not (buf := self._media_group_buffers.pop(key, None)):
                return
            content = "\n".join(buf["contents"]) or "[empty message]"
            if await self._handle_message(
                sender_id=buf["sender_id"], chat_id=buf["chat_id"],
                content=content, media=list(dict.fromkeys(buf["media"])),
                metadata=buf["metadata"],
                session_key=buf.get("session_key"),
            ):
                self._record_inbound_success()
        finally:
            self._media_group_tasks.pop(key, None)

    def _start_typing(self, chat_id: str) -> None:
        """Start sending 'typing...' indicator for a chat."""
        # Cancel any existing typing task for this chat
        self._stop_typing(chat_id)
        self._typing_tasks[chat_id] = asyncio.create_task(self._typing_loop(chat_id))

    def _stop_typing(self, chat_id: str) -> None:
        """Stop the typing indicator for a chat."""
        task = self._typing_tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

    async def _add_reaction(self, chat_id: str, message_id: int, emoji: str) -> None:
        """Add emoji reaction to a message (best-effort, non-blocking)."""
        if not self._app or not emoji:
            return
        try:
            await self._app.bot.set_message_reaction(
                chat_id=int(chat_id),
                message_id=message_id,
                reaction=[ReactionTypeEmoji(emoji=emoji)],
            )
        except Exception as e:
            logger.debug("Telegram reaction failed: {}", e)

    async def _remove_reaction(self, chat_id: str, message_id: int) -> None:
        """Remove emoji reaction from a message (best-effort, non-blocking)."""
        if not self._app:
            return
        try:
            await self._app.bot.set_message_reaction(
                chat_id=int(chat_id),
                message_id=message_id,
                reaction=[],
            )
        except Exception as e:
            logger.debug("Telegram reaction removal failed: {}", e)

    async def _typing_loop(self, chat_id: str) -> None:
        """Repeatedly send 'typing' action until cancelled."""
        try:
            while self._app:
                await self._app.bot.send_chat_action(chat_id=int(chat_id), action="typing")
                await asyncio.sleep(4)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.debug("Typing indicator stopped for {}: {}", chat_id, e)

    @staticmethod
    def _format_telegram_error(exc: Exception) -> str:
        """Return a short, readable error summary for logs."""
        text = str(exc).strip()
        if text:
            return text
        if exc.__cause__ is not None:
            cause = exc.__cause__
            cause_text = str(cause).strip()
            if cause_text:
                return f"{exc.__class__.__name__} ({cause_text})"
            return f"{exc.__class__.__name__} ({cause.__class__.__name__})"
        return exc.__class__.__name__

    def _on_polling_error(self, exc: Exception) -> None:
        """Keep long-polling network failures to a single readable line."""
        self._record_poll_error(exc)
        summary = self._format_telegram_error(exc)
        if isinstance(exc, (NetworkError, TimedOut)):
            logger.warning("Telegram polling network issue: {}", summary)
        else:
            logger.error("Telegram polling error: {}", summary)

    async def _on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log polling / handler errors instead of silently swallowing them."""
        summary = self._format_telegram_error(context.error)

        if isinstance(context.error, (NetworkError, TimedOut)):
            self._record_poll_error(context.error)
            logger.warning("Telegram network issue: {}", summary)
        else:
            self._set_last_error_summary("handler", context.error)
            logger.error("Telegram error: {}", summary)

    def _get_extension(
        self,
        media_type: str,
        mime_type: str | None,
        filename: str | None = None,
    ) -> str:
        """Get file extension based on media type or original filename."""
        if mime_type:
            ext_map = {
                "image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif",
                "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a",
            }
            if mime_type in ext_map:
                return ext_map[mime_type]

        type_map = {"image": ".jpg", "voice": ".ogg", "audio": ".mp3", "file": ""}
        if ext := type_map.get(media_type, ""):
            return ext

        if filename:
            from pathlib import Path

            return "".join(Path(filename).suffixes)

        return ""

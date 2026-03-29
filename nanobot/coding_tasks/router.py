"""Routing helpers for coding-task chat commands."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.coding_tasks.manager import CodexWorkerManager

_START_PREFIX = "开始编程"

_FIELD_PATTERNS = {
    "repo_path": re.compile(r"^(?:仓库|repo|repo_path|路径)\s*[:：=]\s*(.+)$", re.IGNORECASE),
    "goal": re.compile(r"^(?:目标|goal|需求|任务)\s*[:：=]\s*(.+)$", re.IGNORECASE),
    "title": re.compile(r"^(?:标题|title|名称|name)\s*[:：=]\s*(.+)$", re.IGNORECASE),
}


@dataclass(slots=True)
class ParsedCodingTaskRequest:
    """Structured request extracted from a natural-language chat message."""

    repo_path: str
    goal: str
    title: str | None = None


def is_start_coding_request(text: str) -> bool:
    """Return True when a message asks nanobot to start a coding task."""
    return text.strip().startswith(_START_PREFIX)


def parse_start_coding_request(text: str) -> ParsedCodingTaskRequest | None:
    """Parse a natural-language start request into repo path and goal."""
    body = text.strip()
    if not body.startswith(_START_PREFIX):
        return None

    body = body[len(_START_PREFIX) :].strip()
    body = body.lstrip(":：").strip()
    if not body:
        return None

    fields: dict[str, str] = {}
    for line in (line.strip() for line in body.splitlines()):
        if not line:
            continue
        for key, pattern in _FIELD_PATTERNS.items():
            match = pattern.match(line)
            if match:
                fields[key] = match.group(1).strip()
                break

    repo_path = fields.get("repo_path")
    goal = fields.get("goal")
    title = fields.get("title") or None

    if repo_path and goal:
        return ParsedCodingTaskRequest(repo_path=repo_path, goal=goal, title=title)

    try:
        tokens = shlex.split(body)
    except ValueError:
        tokens = body.split()

    if not tokens:
        return None

    candidate_repo = tokens[0].strip()
    if not _looks_like_repo_path(candidate_repo):
        return None

    goal = " ".join(tokens[1:]).strip()
    if not goal:
        return None

    return ParsedCodingTaskRequest(repo_path=candidate_repo, goal=goal, title=title)


def register_coding_task_commands(router: CommandRouter, manager: CodexWorkerManager) -> None:
    """Register chat-level interceptors for coding-task lifecycle actions."""
    router.intercept(_make_start_coding_handler(manager))


def _make_start_coding_handler(manager: CodexWorkerManager):
    async def _handle_start_coding(ctx: CommandContext) -> OutboundMessage | None:
        msg = ctx.msg
        if msg.channel != "telegram":
            return None
        if msg.metadata.get("is_group", True):
            return None
        if not is_start_coding_request(ctx.raw):
            return None

        parsed = parse_start_coding_request(ctx.raw)
        if parsed is None:
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "请用以下格式创建编程任务：\n"
                    "开始编程 仓库路径 任务目标\n\n"
                    "或：\n"
                    "开始编程\n"
                    "仓库: /path/to/repo\n"
                    "目标: 修复某个问题"
                ),
                metadata={"render_as": "text"},
            )

        task = manager.create_task(
            repo_path=parsed.repo_path,
            goal=parsed.goal,
            title=parsed.title,
            metadata={
                "origin_channel": msg.channel,
                "origin_chat_id": msg.chat_id,
                "origin_session_key": msg.session_key,
                "requested_via": "telegram_private_chat",
                "message_id": msg.metadata.get("message_id"),
            },
        )
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=(
                "已创建编程任务\n"
                f"任务ID: {task.id}\n"
                f"状态: {task.status}\n"
                f"仓库: {task.repo_path}\n"
                f"目标: {task.goal}"
            ),
            metadata={"render_as": "text"},
        )

    return _handle_start_coding


def _looks_like_repo_path(token: str) -> bool:
    return token.startswith(("/", "~", "./", "../")) or "/" in token

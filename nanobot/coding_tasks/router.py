"""Routing helpers for coding-task chat commands."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from nanobot.bus.events import OutboundMessage
from nanobot.command.router import CommandContext, CommandRouter
from nanobot.coding_tasks.harness import detect_repo_harness
from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.policy import CodingTaskPolicy
from nanobot.coding_tasks.progress import CodexProgressMonitor
from nanobot.coding_tasks.repo_resolver import RepoRefResolver
from nanobot.coding_tasks.reporting import build_waiting_user_report
from nanobot.coding_tasks.worker import CodexWorkerLauncher

_START_PREFIX = "开始编程"
_SLASH_START_PATTERN = re.compile(r"^/coding(?:@[A-Za-z0-9_]+)?(?:\s|$)")
_SLASH_STATUS_PATTERN = re.compile(r"^/coding(?:@[A-Za-z0-9_]+)?\s+status\s*$", re.IGNORECASE)
_STATUS_COMMANDS = {"状态"}
_RESUME_COMMANDS = {"继续"}
_RESUME_EXISTING_COMMANDS = {"继续旧任务"}
_START_NEW_GOAL_COMMANDS = {"按新任务开始", "开始新任务"}
_CANCEL_COMMANDS = {"取消"}
_STOP_COMMANDS = {"停止"}
_ACTIVE_HARNESS_CONFLICT_REASON = "repo_active_harness"
_COMPLETED_HARNESS_CONFLICT_REASON = "repo_completed_harness"
_HARNESS_CONFLICT_REASONS = {
    _ACTIVE_HARNESS_CONFLICT_REASON,
    _COMPLETED_HARNESS_CONFLICT_REASON,
}

_FIELD_PATTERNS = {
    "repo_path": re.compile(r"^(?:仓库|repo|repo_path|路径)\s*[:：=]\s*(.+)$", re.IGNORECASE),
    "goal": re.compile(r"^(?:目标|goal|需求|任务)\s*[:：=]\s*(.+)$", re.IGNORECASE),
    "title": re.compile(r"^(?:标题|title|名称|name)\s*[:：=]\s*(.+)$", re.IGNORECASE),
}
_SLASH_CONTROL_ACTIONS = {"list", "status", "pause", "resume", "stop"}


@dataclass(slots=True)
class ParsedCodingTaskRequest:
    """Structured request extracted from a natural-language chat message."""

    repo_ref: str
    goal: str
    title: str | None = None


@dataclass(slots=True)
class ParsedSlashCodingCommand:
    """Structured slash subcommand for `/coding` control flows."""

    action: str
    index: int | None = None
    error: str | None = None


def is_explicit_coding_entry(text: str) -> bool:
    """Return True when a message explicitly enters coding-task mode."""
    body = text.strip()
    return body.startswith(_START_PREFIX) or _SLASH_START_PATTERN.match(body) is not None


def is_coding_status_request(text: str) -> bool:
    """Return True when a message explicitly asks for coding-task status."""
    return _SLASH_STATUS_PATTERN.match(text.strip()) is not None


def parse_slash_coding_command(text: str) -> ParsedSlashCodingCommand | None:
    """Parse `/coding <subcommand> [index]` commands used for task control."""
    body = text.strip()
    slash_match = _SLASH_START_PATTERN.match(body)
    if slash_match is None:
        return None
    remainder = body[slash_match.end() :].strip()
    if not remainder:
        return None
    try:
        tokens = shlex.split(remainder)
    except ValueError:
        tokens = remainder.split()
    if not tokens:
        return None
    action = tokens[0].lower()
    if action not in _SLASH_CONTROL_ACTIONS:
        return None
    if action == "list":
        if len(tokens) != 1:
            return ParsedSlashCodingCommand(action=action, error="用法: /coding list")
        return ParsedSlashCodingCommand(action=action)
    if len(tokens) > 2:
        return ParsedSlashCodingCommand(action=action, error=f"用法: /coding {action} [index]")
    if len(tokens) == 2:
        try:
            index = int(tokens[1])
        except ValueError:
            return ParsedSlashCodingCommand(action=action, error="index 必须是从 1 开始的数字。")
        if index < 1:
            return ParsedSlashCodingCommand(action=action, error="index 必须是从 1 开始的数字。")
        return ParsedSlashCodingCommand(action=action, index=index)
    return ParsedSlashCodingCommand(action=action)


def is_start_coding_request(text: str) -> bool:
    """Backward-compatible alias for explicit coding entry detection."""
    return is_explicit_coding_entry(text)


def _strip_explicit_coding_entry(text: str) -> str | None:
    body = text.strip()
    if body.startswith(_START_PREFIX):
        return body[len(_START_PREFIX) :].strip().lstrip(":：").strip()
    slash_match = _SLASH_START_PATTERN.match(body)
    if slash_match is not None:
        return body[slash_match.end() :].strip().lstrip(":：").strip()
    return None


def extract_coding_task_slots(
    text: str,
    *,
    repo_resolver: RepoRefResolver | None = None,
) -> ParsedCodingTaskRequest | None:
    """Extract repo ref and goal from an explicit Telegram coding command."""
    body = _strip_explicit_coding_entry(text)
    if body is None:
        return None
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

    repo_ref = fields.get("repo_path")
    goal = fields.get("goal")
    title = fields.get("title") or None

    if repo_ref and goal:
        return ParsedCodingTaskRequest(repo_ref=repo_ref, goal=goal, title=title)

    try:
        tokens = shlex.split(body)
    except ValueError:
        tokens = body.split()

    if not tokens:
        return None

    repo_ref = tokens[0].strip()
    remainder = body[len(repo_ref) :].strip() if body.startswith(repo_ref) else " ".join(tokens[1:]).strip()
    if remainder.startswith("的"):
        remainder = remainder[1:].strip()
    goal = remainder.strip()
    if not goal:
        return None

    return ParsedCodingTaskRequest(repo_ref=repo_ref, goal=goal, title=title)


def parse_start_coding_request(
    text: str,
    *,
    repo_resolver: RepoRefResolver | None = None,
) -> ParsedCodingTaskRequest | None:
    """Backward-compatible wrapper around the unified coding-task extractor."""
    return extract_coding_task_slots(text, repo_resolver=repo_resolver)


def detect_coding_task_intent(
    text: str,
    *,
    repo_resolver: RepoRefResolver | None = None,
) -> bool:
    """Return True when an explicit Telegram coding entry contains extractable task slots."""
    if not is_explicit_coding_entry(text):
        return False
    return extract_coding_task_slots(text, repo_resolver=repo_resolver) is not None


def resolve_repo_ref(
    repo_ref: str,
    *,
    repo_resolver: RepoRefResolver | None = None,
) -> tuple[str | None, str | None]:
    """Resolve a repo ref into a validated local directory path."""
    raw = repo_ref.strip()
    if not raw:
        return None, "仓库路径不能为空。"
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        return None, "当前只支持本地仓库路径，不支持 URL。"

    resolver = repo_resolver or RepoRefResolver()
    resolved = resolver.resolve(raw)
    if not resolved.exists():
        return None, f"仓库路径不存在: {resolved}"
    if not resolved.is_dir():
        return None, f"仓库路径不是目录: {resolved}"
    return str(resolved), None


def validate_repo_path(
    repo_path: str,
    *,
    repo_resolver: RepoRefResolver | None = None,
) -> tuple[str | None, str | None]:
    """Backward-compatible wrapper for repo reference resolution."""
    return resolve_repo_ref(repo_path, repo_resolver=repo_resolver)


def register_coding_task_commands(
    router: CommandRouter,
    manager: CodexWorkerManager,
    *,
    launcher: CodexWorkerLauncher | None = None,
    monitor: CodexProgressMonitor | None = None,
    policy: CodingTaskPolicy | None = None,
    repo_resolver: RepoRefResolver | None = None,
) -> None:
    """Register chat-level interceptors for coding-task lifecycle actions."""
    task_policy = policy or CodingTaskPolicy(manager)
    resolver = repo_resolver or RepoRefResolver()
    router.intercept(
        _make_start_coding_handler(
            manager,
            task_policy,
            launcher=launcher,
            repo_resolver=resolver,
        )
    )
    router.intercept(
        _make_control_handler(manager, task_policy, launcher=launcher, monitor=monitor)
    )


def _make_start_coding_handler(
    manager: CodexWorkerManager,
    policy: CodingTaskPolicy,
    *,
    launcher: CodexWorkerLauncher | None = None,
    repo_resolver: RepoRefResolver | None = None,
):
    resolver = repo_resolver or RepoRefResolver()

    async def _handle_start_coding(ctx: CommandContext) -> OutboundMessage | None:
        msg = ctx.msg
        if msg.channel != "telegram":
            return None
        if msg.metadata.get("is_group", True):
            return None
        if parse_slash_coding_command(ctx.raw) is not None:
            return None
        if not is_explicit_coding_entry(ctx.raw):
            return None
        if not detect_coding_task_intent(ctx.raw, repo_resolver=resolver):
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "请用以下格式创建编程任务：\n"
                    "开始编程 仓库路径 任务目标\n\n"
                    "或：\n"
                    "开始编程 仓库名 任务目标\n\n"
                    "或：\n"
                    "/coding 仓库名 任务目标\n\n"
                    "或：\n"
                    "开始编程\n"
                    "仓库: codex-remote\n"
                    "目标: 修复某个问题"
                ),
                metadata={"render_as": "text"},
            )

        parsed = extract_coding_task_slots(ctx.raw, repo_resolver=resolver)
        if parsed is None:
            return None

        if active_task := policy.blocking_active_task():
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "当前已有一个活跃的编程任务，MVP 模式下一次只支持一个。\n"
                    f"任务ID: {active_task.id}\n"
                    f"状态: {active_task.status}\n"
                    f"仓库: {active_task.repo_path}\n"
                    "请先发送“状态”查看进度，或发送“取消”结束当前任务。"
                ),
                metadata={"render_as": "text"},
            )

        repo_path, validation_error = resolve_repo_ref(parsed.repo_ref, repo_resolver=resolver)
        if validation_error:
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=validation_error,
                metadata={"render_as": "text"},
            )

        harness = detect_repo_harness(repo_path)
        task = manager.create_task(
            repo_path=repo_path,
            goal=parsed.goal,
            title=parsed.title,
            harness_state=harness.harness_state,
            metadata={
                "origin_channel": msg.channel,
                "origin_chat_id": msg.chat_id,
                "origin_session_key": msg.session_key,
                "requested_via": "telegram_private_chat",
                "message_id": msg.metadata.get("message_id"),
            },
        )
        if harness.harness_state == "active":
            conflict_reason = _ACTIVE_HARNESS_CONFLICT_REASON
            waiting_summary = "仓库里已有未完成的 harness，等待你确认继续旧任务还是按新任务开始。"
            task = manager.update_metadata(
                task.id,
                updates={
                    "harness_conflict_reason": conflict_reason,
                    "existing_harness_summary": harness.summary,
                    "harness_conflict_resolution": "resume_existing",
                },
            )
            waiting = manager.mark_waiting_user(
                task.id,
                summary=waiting_summary,
            )
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=build_waiting_user_report(waiting),
                metadata={"render_as": "text"},
            )

        if launcher is None:
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

        try:
            launched = launcher.launch_task(task.id)
        except Exception as exc:
            failed = manager.mark_failed(
                task.id,
                summary=f"Automatic Telegram launch failed: {type(exc).__name__}: {exc}",
            )
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "已创建编程任务，但自动启动失败\n"
                    f"任务ID: {failed.id}\n"
                    f"状态: {failed.status}\n"
                    f"仓库: {failed.repo_path}\n"
                    f"目标: {failed.goal}\n"
                    f"错误: {type(exc).__name__}: {exc}\n"
                    "可发送“继续”重试启动，或使用 CLI 手动运行该任务。"
                ),
                metadata={"render_as": "text"},
            )

        updated = launched.task
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=(
                "已创建并启动编程任务\n"
                f"任务ID: {updated.id}\n"
                f"状态: {updated.status}\n"
                f"仓库: {updated.repo_path}\n"
                f"目标: {updated.goal}\n"
                f"复用 tmux: {'yes' if launched.session_reused else 'no'}\n"
                f"Harness 状态: {updated.harness_state}"
            ),
            metadata={"render_as": "text"},
        )

    return _handle_start_coding


def _make_control_handler(
    manager: CodexWorkerManager,
    policy: CodingTaskPolicy,
    *,
    launcher: CodexWorkerLauncher | None = None,
    monitor: CodexProgressMonitor | None = None,
):
    async def _handle_control(ctx: CommandContext) -> OutboundMessage | None:
        msg = ctx.msg
        if msg.channel != "telegram":
            return None
        if msg.metadata.get("is_group", True):
            return None

        command = ctx.raw.strip()
        slash_command = parse_slash_coding_command(command)
        if slash_command and slash_command.error:
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=slash_command.error,
                metadata={"render_as": "text"},
            )
        is_status_request = command in _STATUS_COMMANDS or (slash_command is not None and slash_command.action == "status")
        is_list_request = slash_command is not None and slash_command.action == "list"
        is_pause_request = slash_command is not None and slash_command.action == "pause"
        is_resume_request = command in _RESUME_COMMANDS or (slash_command is not None and slash_command.action == "resume")
        is_stop_request = command in _STOP_COMMANDS or (slash_command is not None and slash_command.action == "stop")
        if not (is_status_request or is_list_request or is_pause_request or is_resume_request or is_stop_request) and command not in _RESUME_EXISTING_COMMANDS | _START_NEW_GOAL_COMMANDS | _CANCEL_COMMANDS:
            return None

        if is_list_request:
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=_format_task_list(policy, msg.channel, msg.chat_id, manager),
                metadata={"render_as": "text"},
            )

        indexed_task = None
        if slash_command is not None and slash_command.index is not None:
            indexed_task = policy.task_for_origin_index(msg.channel, msg.chat_id, slash_command.index)
            if indexed_task is None:
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=f"找不到第 {slash_command.index} 个编程任务。先发送 `/coding list` 查看列表。",
                    metadata={"render_as": "text"},
                )

        task = indexed_task or policy.select_control_task(msg.channel, msg.chat_id)
        if task is None:
            latest_origin = policy.latest_origin_task(msg.channel, msg.chat_id)
            if is_resume_request and latest_origin and latest_origin.status == "cancelled":
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=(
                        "最近的编程任务已经取消，不能直接继续。\n"
                        f"任务ID: {latest_origin.id}\n"
                        "请重新发送“开始编程 ...”显式创建新任务。"
                    ),
                    metadata={"render_as": "text"},
                )
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="当前私聊里还没有可控制的编程任务。先发送“开始编程 ...”创建一个任务。",
                metadata={"render_as": "text"},
            )

        if is_status_request:
            report = monitor.build_task_report(task.id) if monitor else None
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=_format_task_status(
                    task,
                    report_summary=report.summary if report else "",
                    recoverable=task.id in {item.id for item in manager.recoverable_tasks()},
                ),
                metadata={"render_as": "text"},
            )

        if _is_harness_conflict_task(task):
            if is_resume_request:
                conflict_note = (
                    "这个仓库里已有已完成的 harness，上下文切换需要你明确选择。\n"
                    "回复“继续旧任务”沿用旧 harness 的上下文继续工作，或回复“按新任务开始”按这次的新目标启动。"
                    if task.metadata.get("harness_conflict_reason") == _COMPLETED_HARNESS_CONFLICT_REASON
                    else "这个仓库里还有旧 harness，继续动作需要你明确选择。\n"
                    "回复“继续旧任务”继续原来的 harness，或回复“按新任务开始”按这次的新目标启动。"
                )
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=conflict_note,
                    metadata={"render_as": "text"},
                )

            if command in _RESUME_EXISTING_COMMANDS | _START_NEW_GOAL_COMMANDS:
                resolution = "start_new_goal" if command in _START_NEW_GOAL_COMMANDS else "resume_existing"
                control = "start_new_goal" if resolution == "start_new_goal" else "resume_existing"
                manager.record_user_control(task.id, control)
                manager.update_metadata(
                    task.id,
                    updates={"harness_conflict_resolution": resolution},
                )
                if launcher:
                    launched = launcher.launch_task(task.id)
                    updated = launched.task
                    action = "已按新任务启动编程任务" if resolution == "start_new_goal" else "已继续旧任务"
                    reused_text = "yes" if launched.session_reused else "no"
                    session_note = f"\n复用 tmux: {reused_text}"
                    return OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=(
                            f"{action}\n"
                            f"任务ID: {updated.id}\n"
                            f"状态: {updated.status}\n"
                            f"仓库: {updated.repo_path}\n"
                            f"目标: {updated.goal}"
                            f"{session_note}"
                        ),
                        metadata={"render_as": "text"},
                    )

                updated = manager.mark_starting(task.id, summary="Recorded harness conflict choice from Telegram private chat")
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=(
                        "已记录你的选择，但当前运行时没有连接 launcher。\n"
                        f"任务ID: {updated.id}\n"
                        f"状态: {updated.status}\n"
                        "请使用 CLI 手动运行该任务。"
                    ),
                metadata={"render_as": "text"},
                )

        if command in _CANCEL_COMMANDS:
            manager.record_user_control(task.id, "cancel")
            if launcher:
                try:
                    launcher.interrupt_task(task.id)
                except Exception:
                    pass
            updated = manager.cancel_task(task.id, summary="Cancelled from Telegram private chat")
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "已取消编程任务\n"
                    f"任务ID: {updated.id}\n"
                    f"状态: {updated.status}\n"
                    f"仓库: {updated.repo_path}"
                ),
                metadata={"render_as": "text"},
            )

        if is_pause_request:
            if task.status in {"completed", "cancelled"}:
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="这个编程任务已经结束，不能再暂停。先发送 `/coding list` 查看其他任务。",
                    metadata={"render_as": "text"},
                )
            if task.status == "waiting_user":
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=_format_task_status(task, note="当前编程任务已经处于暂停状态"),
                    metadata={"render_as": "text"},
                )
            if task.status == "failed":
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="当前编程任务已经失败，请发送 `/coding resume` 尝试恢复，或发送 `/coding stop` 结束任务。",
                    metadata={"render_as": "text"},
                )
            if launcher:
                launcher.interrupt_task(task.id)
            manager.record_user_control(task.id, "pause")
            updated = manager.mark_waiting_user(task.id, summary="Paused from Telegram /coding")
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "已暂停编程任务\n"
                    f"任务ID: {updated.id}\n"
                    f"状态: {updated.status}\n"
                    f"仓库: {updated.repo_path}"
                ),
                metadata={"render_as": "text"},
            )

        if slash_command is not None and slash_command.action == "stop":
            if task.status in {"completed", "cancelled"}:
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="这个编程任务已经结束，不需要再次停止。先发送 `/coding list` 查看其他任务。",
                    metadata={"render_as": "text"},
                )
            if launcher:
                try:
                    launcher.interrupt_task(task.id)
                except Exception:
                    pass
            manager.record_user_control(task.id, "stop")
            updated = manager.cancel_task(task.id, summary="Stopped from Telegram /coding")
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "已停止编程任务\n"
                    f"任务ID: {updated.id}\n"
                    f"状态: {updated.status}\n"
                    f"仓库: {updated.repo_path}"
                ),
                metadata={"render_as": "text"},
            )

        if is_stop_request:
            if launcher:
                launcher.interrupt_task(task.id)
            manager.record_user_control(task.id, "stop")
            updated = manager.mark_waiting_user(task.id, summary="Stopped from Telegram private chat")
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "已停止编程任务\n"
                    f"任务ID: {updated.id}\n"
                    f"状态: {updated.status}\n"
                    f"仓库: {updated.repo_path}"
                ),
                metadata={"render_as": "text"},
            )

        if task.status in {"waiting_user", "failed"} and is_resume_request:
            manager.record_user_control(task.id, "resume")
            if launcher:
                launched = launcher.launch_task(task.id)
                updated = launched.task
                reused_text = "yes" if launched.session_reused else "no"
                session_note = f"\n复用 tmux: {reused_text}"
            else:
                updated = manager.mark_starting(task.id, summary="Resumed from Telegram private chat")
                session_note = ""
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    "已继续编程任务\n"
                    f"任务ID: {updated.id}\n"
                    f"状态: {updated.status}\n"
                    f"仓库: {updated.repo_path}"
                    f"{session_note}"
                ),
                metadata={"render_as": "text"},
            )
        if is_resume_request:
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=_format_task_status(task, note="当前编程任务不需要继续操作"),
                metadata={"render_as": "text"},
            )

        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=_format_task_status(
                task,
                note="当前编程任务不需要继续操作",
                recoverable=task.id in {item.id for item in manager.recoverable_tasks()},
            ),
            metadata={"render_as": "text"},
        )

    return _handle_control


def _format_task_list(policy: CodingTaskPolicy, channel: str, chat_id: str, manager: CodexWorkerManager) -> str:
    tasks = policy.tasks_for_origin(channel, chat_id)
    if not tasks:
        return "当前私聊里还没有编程任务。先发送“开始编程 ...”或 `/coding <repo> <goal>` 创建一个任务。"
    recoverable_ids = {item.id for item in manager.recoverable_tasks()}
    lines = ["当前编程任务列表"]
    for index, task in enumerate(tasks, start=1):
        repo_name = Path(task.repo_path).name or task.repo_path
        goal = _truncate_line(task.goal, limit=28)
        recoverable = "yes" if task.id in recoverable_ids else "no"
        lines.append(
            f"{index}. [{task.status}] {repo_name} | {goal} | recoverable={recoverable} | id={task.id}"
        )
    lines.append("可用命令: `/coding status 2`、`/coding pause 2`、`/coding resume 2`、`/coding stop 2`")
    return "\n".join(lines)


def _format_task_status(task, *, report_summary: str = "", note: str = "当前编程任务状态", recoverable: bool | None = None) -> str:
    lines = [
        note,
        f"任务ID: {task.id}",
        f"状态: {task.status}",
        f"仓库: {task.repo_path}",
        f"目标: {task.goal}",
    ]
    if recoverable is not None:
        lines.append(f"可恢复: {'yes' if recoverable else 'no'}")
    if task.last_progress_summary:
        lines.append(f"最近进展: {task.last_progress_summary}")
    if report_summary:
        lines.append(f"Live report: {report_summary}")
    if task.tmux_session:
        lines.append(f"tmux: {task.tmux_session}")
    return "\n".join(lines)


def _truncate_line(text: str, *, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _is_harness_conflict_task(task) -> bool:
    return (
        task.status == "waiting_user"
        and task.metadata.get("harness_conflict_reason") in _HARNESS_CONFLICT_REASONS
    )

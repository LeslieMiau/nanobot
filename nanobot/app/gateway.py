"""Gateway runtime bootstrap and orchestration."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Sequence

from rich.console import Console

from nanobot.cli.bootstrap import build_agent_runtime

if TYPE_CHECKING:
    from nanobot.config.schema import Config


def run_gateway(
    *,
    port: int,
    workspace: str | None,
    verbose: bool,
    config_path: str | None,
    console: Console,
    logo: str,
    argv: Sequence[str],
    load_runtime_config: Callable[[str | None, str | None], Config],
    sync_templates: Callable[[Path], Any],
    make_provider: Callable[[Config], Any],
    find_other_gateway_processes: Callable[[], list[tuple[int, str]]],
    gateway_lock_cls: Callable[[Path], Any],
    gateway_lock_path_factory: Callable[[], Path],
    build_cron_execution_message: Callable[[str, str], str],
    build_heartbeat_execution_message: Callable[[str, str], str],
    should_deliver_heartbeat_response: Callable[[str | None], bool],
) -> None:
    """Run the nanobot gateway with injected entrypoint helpers."""
    from loguru import logger

    from nanobot.bus.events import OutboundMessage
    from nanobot.channels.manager import ChannelManager
    from nanobot.cron.types import CronJob
    from nanobot.debug.runtime_diagnostics import build_report, render_failure_brief
    from nanobot.heartbeat.service import HeartbeatService
    from nanobot.repo_sync.service import RepoSyncWatcher
    from nanobot.session.manager import SessionManager

    if verbose:
        import logging

        logging.basicConfig(level=logging.DEBUG)

    config = load_runtime_config(config_path, workspace)
    if others := find_other_gateway_processes():
        console.print("[red]Another nanobot gateway instance is already running.[/red]")
        for pid, command in others:
            console.print(f"  PID {pid}: {command}")
        raise SystemExit(1)

    instance_lock = gateway_lock_cls(gateway_lock_path_factory())
    try:
        instance_lock.acquire()
    except RuntimeError as exc:
        console.print("[red]Another nanobot gateway instance already holds the gateway lock.[/red]")
        raise SystemExit(1) from exc

    try:
        console.print(f"{logo} Starting nanobot gateway on port {port}...")
        sync_templates(config.workspace_path)
        session_manager = SessionManager(config.workspace_path)
        repo_sync_cfg = config.gateway.repo_sync
        legacy_repo_sync_marker = "__repo_sync__::"
        restart_requested = False

        async def request_restart() -> None:
            nonlocal restart_requested
            restart_requested = True

        bus = None

        async def _publish_auto_diagnosis(
            *,
            channel: str,
            chat_id: str,
            title: str,
            details: list[str],
            session_key: str | None = None,
        ) -> None:
            if not chat_id or channel == "cli" or bus is None:
                return
            try:
                report = build_report(
                    workspace=config.workspace_path,
                    limit=3,
                    session_key=session_key,
                )
                content = render_failure_brief(report, title=title, details=details)
            except Exception:
                logger.exception("Failed to build auto-diagnosis report")
                return
            await bus.publish_outbound(OutboundMessage(channel=channel, chat_id=chat_id, content=content))

        async def _publish_notice(
            *,
            channel: str,
            chat_id: str,
            title: str,
            details: list[str],
        ) -> None:
            if not chat_id or channel == "cli" or bus is None:
                return
            lines = [title.strip(), ""]
            lines.extend(f"- {detail}" for detail in details if detail)
            content = "\n".join(lines).rstrip() + "\n"
            await bus.publish_outbound(OutboundMessage(channel=channel, chat_id=chat_id, content=content))

        async def on_message_error(msg, error: Exception) -> None:
            """Deliver a concise auto-diagnosis for normal message failures."""
            if msg.channel == "cli":
                return
            await _publish_auto_diagnosis(
                channel=msg.channel,
                chat_id=msg.chat_id,
                title="nanobot auto-diagnosis: message failure",
                details=[
                    f"Session: `{msg.session_key}`",
                    f"Error: `{type(error).__name__}: {error}`",
                ],
                session_key=msg.session_key,
            )

        runtime = build_agent_runtime(
            config,
            provider_factory=make_provider,
            session_manager=session_manager,
            restart_callback=request_restart,
            error_callback=on_message_error,
        )
        bus = runtime.bus
        provider = runtime.provider
        cron = runtime.cron
        agent = runtime.agent

        async def on_cron_job(job: CronJob) -> str | None:
            """Execute a cron job through the agent."""
            from nanobot.agent.tools.cron import CronTool
            from nanobot.agent.tools.message import MessageTool

            reminder_note = build_cron_execution_message(job.name, job.payload.message)

            async def _silent(*_args, **_kwargs):
                pass

            cron_tool = agent.tools.get("cron")
            cron_token = None
            if isinstance(cron_tool, CronTool):
                cron_token = cron_tool.set_cron_context(True)
            try:
                response = await agent.process_direct(
                    reminder_note,
                    session_key=f"cron:{job.id}",
                    channel=job.payload.channel or "cli",
                    chat_id=job.payload.to or "direct",
                    on_progress=_silent,
                )
            finally:
                if isinstance(cron_tool, CronTool) and cron_token is not None:
                    cron_tool.reset_cron_context(cron_token)

            message_tool = agent.tools.get("message")
            if isinstance(message_tool, MessageTool) and message_tool._sent_in_turn:
                return response

            if job.payload.deliver and job.payload.to and response:
                await bus.publish_outbound(
                    OutboundMessage(
                        channel=job.payload.channel or "cli",
                        chat_id=job.payload.to,
                        content=response,
                    )
                )
            return response

        async def on_cron_error(job: CronJob, error: Exception) -> None:
            """Deliver a concise auto-diagnosis for cron failures."""
            if not (job.payload.deliver and job.payload.to):
                return
            await _publish_auto_diagnosis(
                channel=job.payload.channel or "cli",
                chat_id=job.payload.to,
                title="nanobot auto-diagnosis: cron failure",
                details=[
                    f"Job: `{job.name}` (`{job.id}`)",
                    f"Error: `{type(error).__name__}: {error}`",
                ],
                session_key=f"cron:{job.id}",
            )

        cron.on_job = on_cron_job
        cron.on_error = on_cron_error

        legacy_repo_jobs = [
            job
            for job in cron.list_jobs(include_disabled=True)
            if job.payload.message.startswith(legacy_repo_sync_marker)
        ]
        if legacy_repo_jobs:
            for job in legacy_repo_jobs:
                cron.remove_job(job.id)
            console.print(
                f"[green]✓[/green] Removed {len(legacy_repo_jobs)} legacy repo sync cron job(s)"
            )

        channels = ChannelManager(config, bus)

        def _pick_heartbeat_target() -> tuple[str, str]:
            enabled = set(channels.enabled_channels)
            for item in session_manager.list_sessions():
                key = item.get("key") or ""
                if ":" not in key:
                    continue
                channel_name, chat_id = key.split(":", 1)
                if channel_name in {"cli", "system"}:
                    continue
                if channel_name in enabled and chat_id:
                    return channel_name, chat_id
            return "cli", "direct"

        async def on_heartbeat_execute(tasks: str) -> str:
            channel_name, chat_id = _pick_heartbeat_target()
            heartbeat_content = ""
            heartbeat_file = config.workspace_path / "HEARTBEAT.md"
            if heartbeat_file.exists():
                try:
                    heartbeat_content = heartbeat_file.read_text(encoding="utf-8")
                except Exception:
                    heartbeat_content = ""
            prompt = build_heartbeat_execution_message(tasks, heartbeat_content)

            async def _silent(*_args, **_kwargs):
                pass

            return await agent.process_direct(
                prompt,
                session_key="heartbeat",
                channel=channel_name,
                chat_id=chat_id,
                on_progress=_silent,
            )

        async def on_heartbeat_notify(response: str) -> None:
            if not should_deliver_heartbeat_response(response):
                return
            channel_name, chat_id = _pick_heartbeat_target()
            if channel_name == "cli":
                return
            await bus.publish_outbound(
                OutboundMessage(channel=channel_name, chat_id=chat_id, content=response)
            )

        async def on_heartbeat_error(phase: str, error: Exception) -> None:
            channel_name, chat_id = _pick_heartbeat_target()
            if channel_name == "cli":
                return
            await _publish_auto_diagnosis(
                channel=channel_name,
                chat_id=chat_id,
                title="nanobot auto-diagnosis: heartbeat failure",
                details=[
                    f"Phase: `{phase}`",
                    f"Error: `{type(error).__name__}: {error}`",
                ],
                session_key="heartbeat",
            )

        async def on_heartbeat_recovery(status: str, payload: dict[str, object]) -> None:
            channel_name, chat_id = _pick_heartbeat_target()
            if channel_name == "cli":
                return

            phase = str(payload.get("phase") or "decision")
            retry_delay = payload.get("retry_delay_s")
            retry_delay_text = f"{retry_delay}s" if retry_delay is not None else "unknown"
            latest_error = payload.get("latest_error") or payload.get("error")

            if status == "scheduled":
                await _publish_notice(
                    channel=channel_name,
                    chat_id=chat_id,
                    title="nanobot auto-recovery: heartbeat retry scheduled",
                    details=[
                        f"Phase: `{phase}`",
                        f"Retry delay: `{retry_delay_text}`",
                        "Transient heartbeat failure detected; one automatic retry has been scheduled.",
                    ],
                )
                return

            if status == "recovered":
                await _publish_notice(
                    channel=channel_name,
                    chat_id=chat_id,
                    title="nanobot auto-recovery: heartbeat recovered",
                    details=[
                        f"Phase: `{phase}`",
                        f"Retry delay: `{retry_delay_text}`",
                        "The automatic heartbeat retry succeeded; no manual action is needed right now.",
                    ],
                )
                return

            details = [
                f"Phase: `{phase}`",
                f"Retry delay: `{retry_delay_text}`",
            ]
            if latest_error:
                details.append(f"Latest error: `{latest_error}`")
            details.append(
                "The automatic heartbeat retry did not recover the failure; continue manual troubleshooting."
            )
            await _publish_notice(
                channel=channel_name,
                chat_id=chat_id,
                title="nanobot auto-recovery: heartbeat retry exhausted",
                details=details,
            )

        hb_cfg = config.gateway.heartbeat
        heartbeat = HeartbeatService(
            workspace=config.workspace_path,
            provider=provider,
            model=agent.model,
            on_execute=on_heartbeat_execute,
            on_notify=on_heartbeat_notify,
            on_error=on_heartbeat_error,
            on_recovery=on_heartbeat_recovery,
            interval_s=hb_cfg.interval_s,
            enabled=hb_cfg.enabled,
        )

        repo_sync_watcher: RepoSyncWatcher | None = None
        if repo_sync_cfg.enabled:
            repo_sync_watcher = RepoSyncWatcher(
                repo_path=repo_sync_cfg.repo_path,
                branch=repo_sync_cfg.branch,
                upstream_remote=repo_sync_cfg.upstream_remote,
                upstream_url=repo_sync_cfg.upstream_url,
                push_remote=repo_sync_cfg.push_remote,
                auto_push=repo_sync_cfg.auto_push,
                allow_dirty_worktree=repo_sync_cfg.allow_dirty_worktree,
                interval_s=repo_sync_cfg.watch_interval_s,
                run_on_start=repo_sync_cfg.run_on_start,
            )

        if channels.enabled_channels:
            console.print(f"[green]✓[/green] Channels enabled: {', '.join(channels.enabled_channels)}")
        else:
            console.print("[yellow]Warning: No channels enabled[/yellow]")

        cron_status = cron.status()
        if cron_status["jobs"] > 0:
            console.print(f"[green]✓[/green] Cron: {cron_status['jobs']} scheduled jobs")
        if repo_sync_watcher:
            console.print(f"[green]✓[/green] Repo sync watcher: every {repo_sync_cfg.watch_interval_s}s")
        console.print(f"[green]✓[/green] Heartbeat: every {hb_cfg.interval_s}s")

        async def run() -> None:
            agent_task: asyncio.Task | None = None
            channels_task: asyncio.Task | None = None
            try:
                await cron.start()
                await heartbeat.start()
                if repo_sync_watcher:
                    await repo_sync_watcher.start()
                agent_task = asyncio.create_task(agent.run())
                channels_task = asyncio.create_task(channels.start_all())
                while True:
                    if restart_requested:
                        await asyncio.sleep(0.2)
                        break
                    done, _ = await asyncio.wait(
                        {agent_task, channels_task},
                        timeout=0.5,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if done:
                        break
            except KeyboardInterrupt:
                console.print("\nShutting down...")
            finally:
                if agent_task and not agent_task.done():
                    agent.stop()
                    agent_task.cancel()
                if channels_task and not channels_task.done():
                    channels_task.cancel()
                await asyncio.gather(
                    *(task for task in (agent_task, channels_task) if task),
                    return_exceptions=True,
                )
                await agent.close_mcp()
                heartbeat.stop()
                if repo_sync_watcher:
                    repo_sync_watcher.stop()
                cron.stop()
                agent.stop()
                await channels.stop_all()

        asyncio.run(run())
        if restart_requested:
            instance_lock.release()
            os.execv(sys.executable, [sys.executable, "-m", "nanobot", *argv])
    finally:
        instance_lock.release()

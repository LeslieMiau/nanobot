"""Prompt builders shared by app runtimes and operator flows."""

from __future__ import annotations


def build_heartbeat_execution_message(tasks_summary: str, heartbeat_content: str) -> str:
    """Build the phase 2 heartbeat prompt for the full agent loop."""
    summary = tasks_summary.strip() if tasks_summary.strip() else "(empty)"
    content = heartbeat_content.strip() if heartbeat_content.strip() else "(missing)"
    return (
        "You are executing heartbeat tasks.\n"
        "Use the current local time from the runtime context.\n"
        "Re-evaluate the full HEARTBEAT.md below before acting.\n"
        "Check any referenced marker or output files before execution.\n"
        "Execute only tasks that are actually due right now.\n"
        "Heartbeat is for fuzzy recurring checks or conditional tasks, not strict clock-time delivery.\n"
        "Return only the final user-facing content that should be delivered right now.\n"
        "Do not include execution notes, phase labels, methods, thought process, task recap, or tool narration.\n"
        "If no task is due right now, return exactly NOOP and nothing else.\n\n"
        "Phase 1 summary:\n"
        f"{summary}\n\n"
        "Full HEARTBEAT.md:\n"
        f"{content}"
    )


def build_cron_execution_message(job_name: str, instruction: str) -> str:
    """Build the scheduled-task prompt for the full agent loop."""
    name = job_name.strip() if job_name.strip() else "(unnamed)"
    scheduled_instruction = instruction.strip() if instruction.strip() else "(missing)"
    return (
        "You are executing a scheduled task.\n"
        "Use the current local time from the runtime context.\n"
        "Return only the final user-facing content that should be delivered now.\n"
        "Do not include execution notes, phase labels, methods, thought process, task recap, or tool narration.\n\n"
        "Scheduled task name:\n"
        f"{name}\n\n"
        "Scheduled instruction:\n"
        f"{scheduled_instruction}"
    )


def should_deliver_heartbeat_response(response: str | None) -> bool:
    """Return True only when the heartbeat result should be delivered to the user."""
    if not response:
        return False
    return response.strip().upper() != "NOOP"

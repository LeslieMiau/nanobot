"""Summarize nanobot runtime records for troubleshooting."""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.config.loader import get_config_path, load_config
from nanobot.config.paths import get_workspace_path
from nanobot.utils.helpers import safe_filename

_ISSUE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\berror:",
        r"\bfailed\b",
        r"\bexception\b",
        r"\btraceback\b",
        r"\bforbidden\b",
        r"\btimeout\b",
        r"did not attempt verification",
        r"\[analyze the error above",
        r"\bdirectory not found\b",
        r"\bunknown tool\b",
    )
]


@dataclass(slots=True)
class RuntimePaths:
    """Resolved runtime paths for a nanobot instance."""

    config_path: Path
    config_dir: Path
    workspace: Path
    jobs_path: Path
    gateway_lock_path: Path
    sessions_dir: Path
    memory_path: Path
    history_path: Path


def resolve_runtime_paths(
    config_path: str | Path | None = None,
    workspace: str | Path | None = None,
) -> RuntimePaths:
    """Resolve the main runtime paths from config and workspace."""
    resolved_config = Path(config_path).expanduser() if config_path else get_config_path()
    resolved_config = resolved_config.expanduser()

    if workspace:
        resolved_workspace = Path(workspace).expanduser()
    else:
        try:
            resolved_workspace = load_config(resolved_config).workspace_path
        except Exception:
            resolved_workspace = get_workspace_path()

    config_dir = resolved_config.parent
    return RuntimePaths(
        config_path=resolved_config,
        config_dir=config_dir,
        workspace=resolved_workspace,
        jobs_path=config_dir / "cron" / "jobs.json",
        gateway_lock_path=config_dir / "gateway.lock",
        sessions_dir=resolved_workspace / "sessions",
        memory_path=resolved_workspace / "memory" / "MEMORY.md",
        history_path=resolved_workspace / "memory" / "HISTORY.md",
    )


def build_report(
    *,
    config_path: str | Path | None = None,
    workspace: str | Path | None = None,
    limit: int = 5,
    session_key: str | None = None,
) -> dict[str, Any]:
    """Build a troubleshooting report from runtime records."""
    paths = resolve_runtime_paths(config_path=config_path, workspace=workspace)
    sessions = _scan_sessions(paths.sessions_dir, limit=limit, session_key=session_key)
    cron = _read_jobs(paths.jobs_path, limit=limit)

    report = {
        "paths": {
            "config_path": str(paths.config_path),
            "config_dir": str(paths.config_dir),
            "workspace": str(paths.workspace),
            "jobs_path": str(paths.jobs_path),
            "gateway_lock_path": str(paths.gateway_lock_path),
            "sessions_dir": str(paths.sessions_dir),
            "memory_path": str(paths.memory_path),
            "history_path": str(paths.history_path),
        },
        "gateway_lock": _read_gateway_lock(paths.gateway_lock_path),
        "cron": cron,
        "sessions": sessions,
        "history": _read_history(paths.history_path, limit=limit),
    }
    report["next_checks"] = _build_next_checks(report, limit=limit)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    """Render a troubleshooting report as compact Markdown."""
    paths = report["paths"]
    lock = report["gateway_lock"]
    cron = report["cron"]
    sessions = report["sessions"]
    history = report["history"]

    lines = ["# nanobot runtime diagnostics", ""]
    lines.append("## Paths")
    lines.append(f"- Config: `{paths['config_path']}`")
    lines.append(f"- Workspace: `{paths['workspace']}`")
    lines.append(f"- Cron store: `{paths['jobs_path']}`")
    lines.append(f"- Sessions: `{paths['sessions_dir']}`")
    lines.append("")

    lines.append("## Gateway lock")
    if not lock["exists"]:
        lines.append("- No `gateway.lock` file is present.")
    else:
        pid = lock.get("pid")
        running = lock.get("running")
        state = "running" if running else "not running"
        pid_text = str(pid) if pid is not None else "unparsed"
        lines.append(f"- Lock file exists with PID `{pid_text}` ({state}).")
        if lock.get("stale"):
            lines.append("- The lock looks stale; verify no gateway is active before deleting it.")
    lines.append("")

    lines.append("## Cron")
    if not cron["exists"]:
        lines.append("- Cron store is missing.")
    else:
        lines.append(
            f"- Jobs: `{cron['job_count']}` total, `{cron['enabled_count']}` enabled, "
            f"`{len(cron['failing_jobs'])}` failing."
        )
        for job in cron["failing_jobs"]:
            lines.append(
                f"- Failing job `{job['id']}` `{job['name']}`: "
                f"`{job.get('last_error') or job.get('last_status')}`"
            )
    lines.append("")

    lines.append("## Recent sessions")
    if not sessions["latest"]:
        lines.append("- No session files found.")
    else:
        for item in sessions["latest"]:
            lines.append(
                f"- `{item['key']}` updated `{item['updated_at']}` with "
                f"`{item['message_count']}` messages at `{item['path']}`"
            )
    lines.append("")

    lines.append("## Suspected failures")
    if not sessions["suspected_failures"]:
        lines.append("- No obvious failures matched the built-in heuristics.")
    else:
        for issue in sessions["suspected_failures"]:
            lines.append(
                f"- `{issue['session_key']}` `{issue['timestamp']}` `{issue['role']}`: {issue['summary']}"
            )
            lines.append(f"  Path: `{issue['path']}`")
    lines.append("")

    if sessions.get("focus_session"):
        lines.append("## Focus session")
        focus = sessions["focus_session"]
        lines.append(f"- Key: `{focus['key']}`")
        lines.append(f"- Path: `{focus['path']}`")
        for msg in focus["recent_messages"]:
            lines.append(
                f"- `{msg['timestamp']}` `{msg['role']}`: {msg['summary']}"
            )
        lines.append("")

    lines.append("## Recent history")
    if not history["exists"]:
        lines.append("- `memory/HISTORY.md` is missing.")
    else:
        for entry in history["recent_entries"]:
            lines.append(f"- {entry}")
    lines.append("")

    lines.append("## Next checks")
    for check in report["next_checks"]:
        lines.append(f"- {check}")

    return "\n".join(lines).rstrip() + "\n"


def render_failure_brief(
    report: dict[str, Any],
    *,
    title: str,
    details: list[str] | None = None,
) -> str:
    """Render a concise failure summary suitable for proactive delivery."""
    lines = [title.strip() or "nanobot auto-diagnosis", ""]

    for detail in details or []:
        if detail:
            lines.append(f"- {detail}")

    focus = report.get("sessions", {}).get("focus_session")
    if focus:
        lines.append(f"- Session: `{focus['key']}`")

    issues = report.get("sessions", {}).get("suspected_failures", [])
    if issues:
        lines.append(f"- Top clue: {issues[0]['summary']}")

    failing_jobs = report.get("cron", {}).get("failing_jobs", [])
    if failing_jobs:
        job = failing_jobs[0]
        lines.append(
            f"- Latest failing job: `{job['id']}` `{job['name']}` "
            f"({job.get('last_error') or job.get('last_status') or 'unknown'})"
        )

    next_checks = report.get("next_checks", [])
    if next_checks:
        lines.append(f"- Next check: {next_checks[0]}")

    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for troubleshooting reports."""
    parser = argparse.ArgumentParser(description="Summarize nanobot runtime records.")
    parser.add_argument("--config", help="Path to config.json for the target nanobot instance.")
    parser.add_argument("--workspace", help="Workspace path override.")
    parser.add_argument("--limit", type=int, default=5, help="Max items per report section.")
    parser.add_argument("--session-key", help="Include a detailed tail for one session key.")
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="markdown",
        help="Output format.",
    )
    args = parser.parse_args(argv)

    report = build_report(
        config_path=args.config,
        workspace=args.workspace,
        limit=max(1, args.limit),
        session_key=args.session_key,
    )
    if args.format == "json":
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render_markdown(report), end="")
    return 0


def _read_gateway_lock(path: Path) -> dict[str, Any]:
    raw = ""
    pid = None
    running = None
    if path.exists():
        raw = path.read_text(encoding="utf-8").strip()
        if raw.isdigit():
            pid = int(raw)
            running = _pid_is_running(pid)
    return {
        "exists": path.exists(),
        "path": str(path),
        "raw": raw or None,
        "pid": pid,
        "running": running,
        "stale": bool(path.exists() and pid is not None and running is False),
    }


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_jobs(path: Path, *, limit: int) -> dict[str, Any]:
    if not path.exists():
        return {
            "exists": False,
            "path": str(path),
            "job_count": 0,
            "enabled_count": 0,
            "jobs": [],
            "failing_jobs": [],
        }

    data = json.loads(path.read_text(encoding="utf-8"))
    jobs = []
    for raw in data.get("jobs", []):
        state = raw.get("state", {})
        item = {
            "id": raw["id"],
            "name": raw.get("name", ""),
            "enabled": raw.get("enabled", True),
            "last_status": state.get("lastStatus"),
            "last_error": state.get("lastError"),
            "last_run_at": _format_ms(state.get("lastRunAtMs")),
            "next_run_at": _format_ms(state.get("nextRunAtMs")),
            "channel": raw.get("payload", {}).get("channel"),
            "deliver": raw.get("payload", {}).get("deliver"),
        }
        jobs.append(item)

    failing = [
        job for job in jobs if job.get("last_status") == "error" or job.get("last_error")
    ]
    jobs.sort(key=lambda item: (item["next_run_at"] or "", item["id"]))
    failing.sort(key=lambda item: item.get("last_run_at") or "", reverse=True)

    return {
        "exists": True,
        "path": str(path),
        "job_count": len(jobs),
        "enabled_count": sum(1 for item in jobs if item["enabled"]),
        "jobs": jobs[:limit],
        "failing_jobs": failing[:limit],
    }


def _scan_sessions(
    sessions_dir: Path,
    *,
    limit: int,
    session_key: str | None,
) -> dict[str, Any]:
    if not sessions_dir.exists():
        return {
            "exists": False,
            "path": str(sessions_dir),
            "count": 0,
            "latest": [],
            "suspected_failures": [],
            "focus_session": None,
        }

    session_records = []
    focus = None
    for path in sessions_dir.glob("*.jsonl"):
        record = _read_session(path)
        session_records.append(record)
        if session_key and record["key"] == session_key:
            focus = {
                "key": record["key"],
                "path": record["path"],
                "updated_at": record["updated_at"],
                "recent_messages": record["recent_messages"],
            }

    session_records.sort(key=lambda item: item["updated_at"] or "", reverse=True)
    latest = [
        {
            "key": record["key"],
            "path": record["path"],
            "updated_at": record["updated_at"],
            "message_count": record["message_count"],
        }
        for record in session_records[:limit]
    ]

    issues = []
    for record in session_records:
        if record["issue"]:
            issues.append(record["issue"])
        if len(issues) >= limit:
            break

    return {
        "exists": True,
        "path": str(sessions_dir),
        "count": len(session_records),
        "latest": latest,
        "suspected_failures": issues,
        "focus_session": focus,
    }


def _read_session(path: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    messages: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get("_type") == "metadata":
                metadata = data
            else:
                messages.append(data)

    key = metadata.get("key") or path.stem.replace("_", ":", 1)
    updated_at = metadata.get("updated_at") or (messages[-1].get("timestamp") if messages else None)
    issue = _find_issue(messages, key=key, path=path)

    return {
        "key": key,
        "path": str(path),
        "updated_at": updated_at,
        "message_count": len(messages),
        "recent_messages": [_summarize_message(item) for item in messages[-8:]],
        "issue": issue,
    }


def _find_issue(messages: list[dict[str, Any]], *, key: str, path: Path) -> dict[str, Any] | None:
    for item in reversed(messages):
        role = item.get("role", "")
        if role not in {"assistant", "tool"}:
            continue
        text = item.get("content") or ""
        if not isinstance(text, str) or not _looks_like_issue(text):
            continue
        return {
            "session_key": key,
            "path": str(path),
            "timestamp": item.get("timestamp"),
            "role": role,
            "summary": _trim(text),
        }
    return None


def _looks_like_issue(text: str) -> bool:
    return any(pattern.search(text) for pattern in _ISSUE_PATTERNS)


def _summarize_message(message: dict[str, Any]) -> dict[str, Any]:
    summary = _trim(message.get("content") or "")
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        names = []
        for call in tool_calls:
            fn = call.get("function", {})
            names.append(fn.get("name") or call.get("name") or "unknown")
        summary = f"tool_calls: {', '.join(names)}"
    return {
        "timestamp": message.get("timestamp"),
        "role": message.get("role"),
        "summary": summary or "(empty)",
    }


def _read_history(path: Path, *, limit: int) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path), "recent_entries": []}

    content = path.read_text(encoding="utf-8").strip()
    entries = [entry.strip().replace("\n", " ") for entry in content.split("\n\n") if entry.strip()]
    return {
        "exists": True,
        "path": str(path),
        "recent_entries": [_trim(entry) for entry in entries[-limit:]],
    }


def _build_next_checks(report: dict[str, Any], *, limit: int) -> list[str]:
    checks: list[str] = []
    lock = report["gateway_lock"]
    cron = report["cron"]
    sessions = report["sessions"]

    if lock.get("stale"):
        checks.append("The gateway lock looks stale; confirm no live gateway process before clearing it.")

    for job in cron["failing_jobs"][:limit]:
        session_name = safe_filename(f"cron_{job['id']}") + ".jsonl"
        session_path = Path(report["paths"]["sessions_dir"]) / session_name
        checks.append(
            f"Inspect cron job `{job['id']}` in `{session_path}` for the failing turn and tool output."
        )

    for issue in sessions["suspected_failures"][:limit]:
        checks.append(
            f"Open `{issue['path']}` around `{issue['timestamp']}` to inspect the full failing turn."
        )

    if sessions.get("focus_session"):
        checks.append(
            f"Focus session `{sessions['focus_session']['key']}` already includes a recent tail; "
            "check preceding tool calls if the root cause is still unclear."
        )

    if not checks:
        checks.append(
            "No obvious cron failures or session errors were detected; inspect the target session tail "
            "or reproduce the issue with a narrow request."
        )

    # Deduplicate while preserving order.
    unique: list[str] = []
    for item in checks:
        if item not in unique:
            unique.append(item)
    return unique[:limit]


def _format_ms(value: int | None) -> str | None:
    if not value:
        return None
    return datetime.fromtimestamp(value / 1000).astimezone().isoformat()


def _trim(text: str, width: int = 180) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= width:
        return normalized
    return normalized[: width - 3] + "..."


if __name__ == "__main__":
    raise SystemExit(main())

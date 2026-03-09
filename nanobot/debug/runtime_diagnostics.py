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

_CATEGORY_ORDER = ("config", "tool", "transport", "model", "scheduling", "unknown")
_CATEGORY_RULES: dict[str, list[tuple[re.Pattern[str], int]]] = {
    "config": [
        (re.compile(r"\bnot configured\b|\bmissing\b|\bconfiguration\b|\bconfig\b", re.IGNORECASE), 3),
        (re.compile(r"\bapi key\b|\bcredential\b|\benv(?:ironment)? variable\b", re.IGNORECASE), 3),
        (re.compile(r"\bworkspace\b|\bpath\b", re.IGNORECASE), 1),
    ],
    "tool": [
        (re.compile(r"\bunknown tool\b|\btool timeout\b", re.IGNORECASE), 3),
        (re.compile(r"\bdirectory not found\b|\bfile not found\b|\bpermission denied\b", re.IGNORECASE), 3),
        (re.compile(r"\bcommand failed\b|\bexit code\b|\bexec\b|\bshell\b|\bspawn\b", re.IGNORECASE), 2),
        (re.compile(r"\btraceback\b|\bverification\b", re.IGNORECASE), 1),
    ],
    "transport": [
        (re.compile(r"\btelegram\b|\bslack\b|\bdiscord\b|\bwebhook\b", re.IGNORECASE), 3),
        (re.compile(r"\bdelivery\b|\bdeliver\b|\bsend failed\b|\bchat[-_ ]?id\b|\bchannel\b", re.IGNORECASE), 2),
        (re.compile(r"\bconnection refused\b|\bnetwork\b|\bunreachable\b|\bforbidden\b|\bunauthorized\b", re.IGNORECASE), 2),
    ],
    "model": [
        (re.compile(r"\brate limit\b|\bquota\b|\bcontext length\b|\bmaximum context\b|\btoken limit\b", re.IGNORECASE), 3),
        (re.compile(r"\bmodel\b|\bprovider\b|\bopenai\b|\banthropic\b|\blitellm\b|\bllm\b", re.IGNORECASE), 2),
        (re.compile(r"\bai model\b|\bdecision error\b", re.IGNORECASE), 2),
    ],
    "scheduling": [
        (re.compile(r"\bcron\b|\bheartbeat\b|\bschedule\b", re.IGNORECASE), 2),
        (re.compile(r"\bnext run\b|\blast run\b|\bdisabled\b|\bskipped\b|\bnoop\b", re.IGNORECASE), 2),
        (re.compile(r"\bgateway\.lock\b|\bstale lock\b", re.IGNORECASE), 3),
    ],
}
_CLASSIFICATION_SOURCE_BONUS = {
    "title": 0,
    "detail": 2,
    "session clue": 2,
    "cron error": 2,
    "focus message": 1,
    "history entry": 1,
}
_CATEGORY_SUMMARIES = {
    "config": "The latest failure most likely comes from missing or incorrect configuration.",
    "tool": "The latest failure most likely comes from a tool call or local execution step.",
    "transport": "The latest failure most likely happened while delivering or routing a message.",
    "model": "The latest failure most likely comes from the model/provider layer.",
    "scheduling": "The latest failure most likely comes from cron, heartbeat, or another scheduling path.",
    "unknown": "The latest failure does not have a strong enough signal yet; inspect the raw session turn.",
}
_CATEGORY_ACTIONS = {
    "config": [
        "Verify required keys, provider settings, and workspace paths in `config.json`.",
        "Check that any referenced files, directories, and env vars actually exist.",
    ],
    "tool": [
        "Open the failing session turn and inspect the exact tool input and tool result.",
        "Re-run the failing tool step with narrower input to separate tool failure from model planning.",
    ],
    "transport": [
        "Verify channel credentials, target chat IDs, and outbound delivery permissions.",
        "Check whether the transport-specific sender returned a network or authorization error.",
    ],
    "model": [
        "Verify provider credentials, model availability, and current quota or rate-limit state.",
        "Retry with a shorter prompt or a fallback model to confirm whether the provider path is unstable.",
    ],
    "scheduling": [
        "Inspect `cron/jobs.json` and the matching session file for the skipped or failing run.",
        "Check heartbeat rules, cron schedule metadata, and any stale `gateway.lock` state.",
    ],
    "unknown": [
        "Open the focus session around the failing turn and inspect the preceding tool calls.",
        "Reproduce the issue with a narrower request so the failing step is isolated in one session turn.",
    ],
}
_SAFE_NEXT_ACTIONS = {
    "config": "check_config",
    "tool": "inspect_session",
    "transport": "check_transport",
    "model": "retry_later",
    "scheduling": "inspect_schedule",
    "unknown": "inspect_session",
}
_REMEDIATION_TEMPLATES = {
    "config": {
        "repairability": "high",
        "urgency": "medium",
        "top_fix": "Check `config.json`, required secrets, and referenced paths before rerunning the same request.",
        "fix_steps": [
            "Verify provider/model settings and any required API keys or env vars.",
            "Confirm workspace paths, files, and directories referenced by the failing turn exist.",
            "After fixing configuration, rerun the same request or scheduled job once.",
        ],
    },
    "tool": {
        "repairability": "medium",
        "urgency": "medium",
        "top_fix": "Inspect the failing tool call in the session log, then rerun only that narrower step.",
        "fix_steps": [
            "Open the failing session turn and inspect the tool input, tool result, and surrounding context.",
            "Confirm whether the failure came from missing files, permissions, or a bad tool argument.",
            "Retry the smallest failing step after correcting the local precondition.",
        ],
    },
    "transport": {
        "repairability": "medium",
        "urgency": "high",
        "top_fix": "Verify channel credentials and target delivery metadata before retrying outbound delivery.",
        "fix_steps": [
            "Check the channel credential, destination chat ID, and delivery permissions.",
            "Inspect the transport-specific sender output for network, auth, or forbidden errors.",
            "Retry delivery once after confirming the target is reachable and authorized.",
        ],
    },
    "model": {
        "repairability": "medium",
        "urgency": "medium",
        "top_fix": "Verify provider health and quota, then retry later or with a smaller prompt.",
        "fix_steps": [
            "Check provider credentials, model availability, and current quota or rate-limit state.",
            "If the prompt is large, retry with a shorter request or a fallback model.",
            "If the provider is degraded, wait briefly before retrying the same turn.",
        ],
    },
    "scheduling": {
        "repairability": "high",
        "urgency": "high",
        "top_fix": "Inspect the scheduling path first: `cron/jobs.json`, the matching session log, and any stale `gateway.lock` state.",
        "fix_steps": [
            "Check whether the job or heartbeat run was skipped, disabled, or blocked by stale runtime state.",
            "Inspect the matching cron or heartbeat session file for the exact failing turn.",
            "After correcting the schedule or lock issue, rerun the job once manually if needed.",
        ],
    },
    "unknown": {
        "repairability": "low",
        "urgency": "low",
        "top_fix": "Inspect the raw session turn first; there is not enough signal yet for a safe targeted fix.",
        "fix_steps": [
            "Open the focus session around the failing turn and inspect the preceding tool calls.",
            "Reproduce the problem with a narrower request to isolate one failing step.",
            "Only after isolating the failure should you decide whether to reconfigure, retry, or edit code.",
        ],
    },
}


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
    report["diagnosis"] = _classify_failure(report)
    report["remediation"] = _build_remediation(report, report["diagnosis"])
    return report


def render_markdown(report: dict[str, Any]) -> str:
    """Render a troubleshooting report as compact Markdown."""
    paths = report["paths"]
    lock = report["gateway_lock"]
    cron = report["cron"]
    sessions = report["sessions"]
    history = report["history"]
    diagnosis = report.get("diagnosis")
    remediation = report.get("remediation")

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

    lines.append("## Diagnosis")
    if not diagnosis:
        lines.append("- No diagnosis summary is available.")
    else:
        lines.append(f"- Category: `{diagnosis['category']}` ({diagnosis['confidence']})")
        lines.append(f"- Summary: {diagnosis['summary']}")
        for signal in diagnosis.get("signals", [])[:2]:
            lines.append(f"- Signal: {signal}")
        for action in diagnosis.get("recommended_actions", [])[:2]:
            lines.append(f"- Suggested action: {action}")
    lines.append("")

    lines.append("## Remediation")
    if not remediation:
        lines.append("- No remediation plan is available.")
    else:
        lines.append(f"- Safe next action: `{remediation['safe_next_action']}`")
        lines.append(
            f"- Repairability: `{remediation['repairability']}`, urgency: `{remediation['urgency']}`"
        )
        lines.append(f"- Top fix: {remediation['top_fix']}")
        for step in remediation.get("fix_steps", [])[:2]:
            lines.append(f"- Fix step: {step}")
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
    diagnosis = _classify_failure(report, title=title, details=details)
    remediation = _build_remediation(report, diagnosis)

    for detail in details or []:
        if detail:
            lines.append(f"- {detail}")

    focus = report.get("sessions", {}).get("focus_session")
    if focus:
        lines.append(f"- Session: `{focus['key']}`")

    if diagnosis:
        lines.append(
            f"- Likely category: `{diagnosis['category']}` ({diagnosis['confidence']})"
        )
        if diagnosis.get("signals"):
            lines.append(f"- Why: {diagnosis['signals'][0]}")
    if remediation:
        lines.append(f"- Safe next action: `{remediation['safe_next_action']}`")
        lines.append(
            f"- Repairability: `{remediation['repairability']}`, urgency: `{remediation['urgency']}`"
        )

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
    if remediation:
        lines.append(f"- Top fix: {remediation['top_fix']}")

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


def _classify_failure(
    report: dict[str, Any],
    *,
    title: str | None = None,
    details: list[str] | None = None,
) -> dict[str, Any]:
    scores = {category: 0 for category in _CATEGORY_ORDER}
    signals: dict[str, list[str]] = {category: [] for category in _CATEGORY_ORDER}
    seen_signals: set[tuple[str, str]] = set()

    def add(category: str, score: int, reason: str) -> None:
        scores[category] += score
        marker = (category, reason)
        if marker in seen_signals:
            return
        seen_signals.add(marker)
        signals[category].append(reason)

    lock = report.get("gateway_lock", {})
    if lock.get("stale"):
        add("scheduling", 4, "`gateway.lock` looks stale, so scheduled work may be blocked.")

    focus = report.get("sessions", {}).get("focus_session") or {}
    focus_key = str(focus.get("key") or "")
    if focus_key == "heartbeat":
        add("scheduling", 1, "The focus session is `heartbeat`.")
    elif focus_key.startswith("cron:"):
        add("scheduling", 1, "The focus session comes from a cron run.")

    failing_jobs = report.get("cron", {}).get("failing_jobs", [])
    if failing_jobs:
        add("scheduling", 1, "`cron/jobs.json` contains recent failing jobs.")

    for source_name, text in _classification_sources(report, title=title, details=details):
        bonus = _CLASSIFICATION_SOURCE_BONUS[source_name]
        snippet = _trim(text, width=100)
        for category, rules in _CATEGORY_RULES.items():
            for pattern, weight in rules:
                if not pattern.search(text):
                    continue
                add(category, weight + bonus, f"{source_name.capitalize()} mentions `{snippet}`.")
                break

    ranked = sorted(
        _CATEGORY_ORDER,
        key=lambda category: (scores[category], -_CATEGORY_ORDER.index(category)),
        reverse=True,
    )
    category = ranked[0]
    top_score = scores[category]
    runner_up = scores[ranked[1]] if len(ranked) > 1 else 0

    if top_score <= 0:
        category = "unknown"
        confidence = "low"
    elif top_score >= 6 or (top_score >= 4 and top_score - runner_up >= 2):
        confidence = "high"
    elif top_score >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "category": category,
        "confidence": confidence,
        "summary": _CATEGORY_SUMMARIES[category],
        "signals": signals[category][:3],
        "recommended_actions": _recommended_actions(report, category)[:3],
        "scores": {name: value for name, value in scores.items() if value > 0},
    }


def _classification_sources(
    report: dict[str, Any],
    *,
    title: str | None,
    details: list[str] | None,
) -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []
    if title:
        sources.append(("title", title))
    for detail in details or []:
        if detail:
            sources.append(("detail", detail))

    for issue in report.get("sessions", {}).get("suspected_failures", [])[:3]:
        summary = issue.get("summary")
        if summary:
            sources.append(("session clue", str(summary)))

    focus = report.get("sessions", {}).get("focus_session") or {}
    for message in focus.get("recent_messages", [])[-3:]:
        summary = message.get("summary")
        if summary:
            sources.append(("focus message", str(summary)))

    for job in report.get("cron", {}).get("failing_jobs", [])[:2]:
        error_text = job.get("last_error") or job.get("last_status")
        if error_text:
            sources.append(("cron error", str(error_text)))

    for entry in report.get("history", {}).get("recent_entries", [])[-2:]:
        if entry:
            sources.append(("history entry", str(entry)))

    return sources


def _recommended_actions(report: dict[str, Any], category: str) -> list[str]:
    actions = list(_CATEGORY_ACTIONS[category])
    for check in report.get("next_checks", []):
        actions.append(check)

    unique: list[str] = []
    for action in actions:
        if action not in unique:
            unique.append(action)
    return unique


def _build_remediation(report: dict[str, Any], diagnosis: dict[str, Any] | None) -> dict[str, Any]:
    if not diagnosis:
        diagnosis = _classify_failure(report)

    category = diagnosis["category"]
    template = _REMEDIATION_TEMPLATES[category]
    safe_next_action = _safe_next_action(report, diagnosis)
    urgency = _remediation_urgency(report, diagnosis, template["urgency"])
    fix_steps = list(template["fix_steps"])
    for action in diagnosis.get("recommended_actions", [])[:2]:
        if action not in fix_steps:
            fix_steps.append(action)
    for check in report.get("next_checks", [])[:2]:
        if check not in fix_steps:
            fix_steps.append(check)

    return {
        "safe_next_action": safe_next_action,
        "repairability": _remediation_repairability(diagnosis, template["repairability"]),
        "urgency": urgency,
        "top_fix": template["top_fix"],
        "fix_steps": fix_steps[:4],
    }


def _safe_next_action(report: dict[str, Any], diagnosis: dict[str, Any]) -> str:
    category = diagnosis["category"]
    if report.get("gateway_lock", {}).get("stale"):
        return "inspect_schedule"
    if diagnosis.get("confidence") == "low" and category not in {"config", "transport"}:
        return "inspect_session"
    return _SAFE_NEXT_ACTIONS[category]


def _remediation_repairability(diagnosis: dict[str, Any], base: str) -> str:
    if diagnosis.get("category") == "unknown":
        return "low"
    if diagnosis.get("confidence") == "low" and base == "high":
        return "medium"
    return base


def _remediation_urgency(report: dict[str, Any], diagnosis: dict[str, Any], base: str) -> str:
    category = diagnosis["category"]
    if report.get("gateway_lock", {}).get("stale"):
        return "high"
    if category == "transport":
        return "high"
    if category == "scheduling" and report.get("cron", {}).get("failing_jobs"):
        return "high"
    if category == "unknown" and diagnosis.get("confidence") == "low":
        return "low"
    return base


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

import json
import os
from pathlib import Path

from nanobot.agent.skills import SkillsLoader
from nanobot.debug.runtime_diagnostics import (
    build_report,
    render_failure_brief,
    render_markdown,
    resolve_runtime_paths,
)


def _write_session(path: Path, key: str, messages: list[dict], *, updated_at: str) -> None:
    lines = [
        {
            "_type": "metadata",
            "key": key,
            "created_at": "2026-03-09T08:00:00+08:00",
            "updated_at": updated_at,
            "metadata": {},
            "last_consolidated": 0,
        },
        *messages,
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for line in lines:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def test_runtime_troubleshooting_skill_is_discoverable() -> None:
    workspace = Path(__file__).resolve().parents[1]
    loader = SkillsLoader(workspace)

    names = {skill["name"] for skill in loader.list_skills(filter_unavailable=False)}

    assert "runtime-troubleshooting" in names


def test_runtime_troubleshooting_skill_loads_content() -> None:
    workspace = Path(__file__).resolve().parents[1]
    loader = SkillsLoader(workspace)

    content = loader.load_skill("runtime-troubleshooting")

    assert content is not None
    assert "python -m nanobot.debug.runtime_diagnostics --format json" in content
    assert "cron/jobs.json" in content
    assert "sessions/*.jsonl" in content
    assert "gateway.lock" in content
    assert "references/playbooks.md" in content


def test_resolve_runtime_paths_uses_workspace_from_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    workspace = tmp_path / "workspace-a"
    config_dir.mkdir()
    config_path = config_dir / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {"defaults": {"workspace": str(workspace)}},
            }
        ),
        encoding="utf-8",
    )

    paths = resolve_runtime_paths(config_path=config_path)

    assert paths.workspace == workspace
    assert paths.jobs_path == config_dir / "cron" / "jobs.json"
    assert paths.gateway_lock_path == config_dir / "gateway.lock"


def test_build_report_summarizes_cron_and_session_issues(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    workspace = tmp_path / "workspace"
    config_dir.mkdir()
    workspace.mkdir()
    config_path = config_dir / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {"defaults": {"workspace": str(workspace)}},
            }
        ),
        encoding="utf-8",
    )

    (config_dir / "gateway.lock").write_text(str(os.getpid()), encoding="utf-8")
    jobs_path = config_dir / "cron" / "jobs.json"
    jobs_path.parent.mkdir(parents=True, exist_ok=True)
    jobs_path.write_text(
        json.dumps(
            {
                "version": 1,
                "jobs": [
                    {
                        "id": "abc12345",
                        "name": "Morning digest",
                        "enabled": True,
                        "schedule": {"kind": "cron", "expr": "0 8 * * *", "tz": "Asia/Shanghai"},
                        "payload": {"kind": "agent_turn", "message": "do thing", "deliver": True, "channel": "telegram", "to": "1"},
                        "state": {
                            "nextRunAtMs": 1773100800000,
                            "lastRunAtMs": 1773014400000,
                            "lastStatus": "error",
                            "lastError": "tool timeout",
                        },
                        "createdAtMs": 1773010000000,
                        "updatedAtMs": 1773014400000,
                        "deleteAfterRun": False,
                    },
                    {
                        "id": "ok678901",
                        "name": "Evening digest",
                        "enabled": True,
                        "schedule": {"kind": "cron", "expr": "0 18 * * *", "tz": "Asia/Shanghai"},
                        "payload": {"kind": "agent_turn", "message": "do other thing", "deliver": True, "channel": "telegram", "to": "1"},
                        "state": {
                            "nextRunAtMs": 1773136800000,
                            "lastRunAtMs": 1773050400000,
                            "lastStatus": "ok",
                            "lastError": None,
                        },
                        "createdAtMs": 1773010000001,
                        "updatedAtMs": 1773050400000,
                        "deleteAfterRun": False,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    _write_session(
        workspace / "sessions" / "telegram_1.jsonl",
        "telegram:1",
        [
            {"role": "user", "content": "why did it fail", "timestamp": "2026-03-09T09:00:00+08:00"},
            {"role": "tool", "content": "Error: Directory not found: /tmp/missing", "timestamp": "2026-03-09T09:00:01+08:00"},
        ],
        updated_at="2026-03-09T09:00:01+08:00",
    )
    _write_session(
        workspace / "sessions" / "heartbeat.jsonl",
        "heartbeat",
        [
            {"role": "assistant", "content": "NOOP", "timestamp": "2026-03-09T08:30:00+08:00"},
        ],
        updated_at="2026-03-09T08:30:00+08:00",
    )
    history_path = workspace / "memory" / "HISTORY.md"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        "[2026-03-09 09:00] Cron abc12345 failed due to timeout.\n\n"
        "[2026-03-09 09:05] User asked for diagnosis.",
        encoding="utf-8",
    )

    report = build_report(config_path=config_path, limit=3)

    assert report["gateway_lock"]["running"] is True
    assert report["cron"]["job_count"] == 2
    assert len(report["cron"]["failing_jobs"]) == 1
    assert report["cron"]["failing_jobs"][0]["id"] == "abc12345"
    assert report["sessions"]["count"] == 2
    assert report["sessions"]["suspected_failures"][0]["session_key"] == "telegram:1"
    assert "Directory not found" in report["sessions"]["suspected_failures"][0]["summary"]
    assert report["diagnosis"]["category"] == "tool"
    assert report["diagnosis"]["confidence"] in {"medium", "high"}
    assert report["remediation"]["safe_next_action"] == "inspect_session"
    assert report["remediation"]["repairability"] == "medium"
    assert report["remediation"]["urgency"] == "medium"
    assert "Inspect the failing tool call" in report["remediation"]["top_fix"]
    assert any("tool" in step.lower() or "session" in step.lower() for step in report["remediation"]["fix_steps"])
    assert report["auto_recovery"]["eligible"] is False
    assert report["auto_recovery"]["scope"] == "cron_turn"
    assert "side-effecting tools" in report["auto_recovery"]["blocked_reason"]
    assert any("tool" in action.lower() or "session" in action.lower() for action in report["diagnosis"]["recommended_actions"])
    assert len(report["history"]["recent_entries"]) == 2
    assert any("abc12345" in item for item in report["next_checks"])


def test_build_report_includes_focus_session_tail_and_markdown(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    workspace = tmp_path / "workspace"
    config_dir.mkdir()
    workspace.mkdir()
    config_path = config_dir / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {"defaults": {"workspace": str(workspace)}},
            }
        ),
        encoding="utf-8",
    )

    _write_session(
        workspace / "sessions" / "heartbeat.jsonl",
        "heartbeat",
        [
            {"role": "user", "content": "tick", "timestamp": "2026-03-09T08:00:00+08:00"},
            {"role": "assistant", "content": "tool_calls: heartbeat", "timestamp": "2026-03-09T08:00:01+08:00"},
            {"role": "tool", "content": "Error: unknown tool", "timestamp": "2026-03-09T08:00:02+08:00"},
        ],
        updated_at="2026-03-09T08:00:02+08:00",
    )

    report = build_report(config_path=config_path, session_key="heartbeat", limit=2)
    markdown = render_markdown(report)

    assert report["sessions"]["focus_session"]["key"] == "heartbeat"
    assert len(report["sessions"]["focus_session"]["recent_messages"]) == 3
    assert "## Focus session" in markdown
    assert "## Diagnosis" in markdown
    assert "## Remediation" in markdown
    assert "## Auto Recovery" in markdown
    assert "Category: `tool`" in markdown
    assert "Safe next action: `inspect_session`" in markdown
    assert "Status: `blocked`" in markdown
    assert "heartbeat" in markdown
    assert "unknown tool" in markdown


def test_render_failure_brief_uses_category_and_next_check() -> None:
    report = {
        "sessions": {
            "focus_session": {"key": "heartbeat"},
            "suspected_failures": [{"summary": "Error: Brave Search API key not configured"}],
        },
        "cron": {
            "failing_jobs": [
                {"id": "abc12345", "name": "Morning digest", "last_error": "tool timeout", "last_status": "error"}
            ]
        },
        "next_checks": ["Open `heartbeat.jsonl` around the failing turn."],
    }

    brief = render_failure_brief(
        report,
        title="nanobot auto-diagnosis: heartbeat failure",
        details=["Phase: `decision`", "Error: `HeartbeatDecisionError: plain text`"],
    )

    assert "nanobot auto-diagnosis: heartbeat failure" in brief
    assert "Phase: `decision`" in brief
    assert "Session: `heartbeat`" in brief
    assert "Likely category: `config`" in brief
    assert "Safe next action: `check_config`" in brief
    assert "Repairability: `high`, urgency: `medium`" in brief
    assert "Auto recovery: `eligible` (`heartbeat_decision`)" in brief
    assert "Retry delay: `15s`" in brief
    assert "Top clue: Error: Brave Search API key not configured" in brief
    assert "Latest failing job: `abc12345` `Morning digest` (tool timeout)" in brief
    assert "Next check: Open `heartbeat.jsonl` around the failing turn." in brief
    assert "Top fix: Check `config.json`, required secrets, and referenced paths before rerunning the same request." in brief


def test_render_failure_brief_classifies_transport_failures_from_details() -> None:
    report = {
        "sessions": {"focus_session": {"key": "telegram:chat-1"}, "suspected_failures": []},
        "cron": {"failing_jobs": []},
        "next_checks": ["Open `telegram_chat-1.jsonl` around the failed send attempt."],
        "history": {"recent_entries": []},
        "gateway_lock": {"stale": False},
    }

    brief = render_failure_brief(
        report,
        title="nanobot auto-diagnosis: message failure",
        details=["Session: `telegram:chat-1`", "Error: `TelegramSendError: forbidden by target chat`"],
    )

    assert "Likely category: `transport`" in brief
    assert "Safe next action: `check_transport`" in brief
    assert "Repairability: `medium`, urgency: `high`" in brief
    assert "Auto recovery: `blocked` (`message_turn`)" in brief
    assert "Recovery block: Automatic retry is blocked because this failure path may already have executed side-effecting tools." in brief
    assert "Top fix: Verify channel credentials and target delivery metadata before retrying outbound delivery." in brief


def test_build_report_marks_stale_gateway_lock_as_high_urgency_schedule_issue(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    workspace = tmp_path / "workspace"
    config_dir.mkdir()
    workspace.mkdir()
    config_path = config_dir / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agents": {"defaults": {"workspace": str(workspace)}},
            }
        ),
        encoding="utf-8",
    )

    (config_dir / "gateway.lock").write_text("999999", encoding="utf-8")
    _write_session(
        workspace / "sessions" / "heartbeat.jsonl",
        "heartbeat",
        [{"role": "assistant", "content": "NOOP", "timestamp": "2026-03-09T08:00:00+08:00"}],
        updated_at="2026-03-09T08:00:00+08:00",
    )

    report = build_report(config_path=config_path, session_key="heartbeat", limit=2)

    assert report["gateway_lock"]["stale"] is True
    assert report["diagnosis"]["category"] == "scheduling"
    assert report["remediation"]["safe_next_action"] == "inspect_schedule"
    assert report["remediation"]["urgency"] == "high"
    assert report["auto_recovery"]["eligible"] is False
    assert report["auto_recovery"]["scope"] == "heartbeat"
    assert "cron/jobs.json" in report["remediation"]["top_fix"]

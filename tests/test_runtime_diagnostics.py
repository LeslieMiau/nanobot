import json
import os
from pathlib import Path

from nanobot.agent.skills import SkillsLoader
from nanobot.debug.runtime_diagnostics import build_report, render_markdown, resolve_runtime_paths


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
    assert "heartbeat" in markdown
    assert "unknown tool" in markdown

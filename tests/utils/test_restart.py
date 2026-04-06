"""Tests for restart notice helpers."""

from __future__ import annotations

import os

from nanobot.utils.restart import (
    RestartNotice,
    consume_restart_notice_from_env,
    format_restart_completed_message,
    is_restart_in_cooldown,
    read_and_clear_restart_marker,
    set_restart_notice_to_env,
    should_show_cli_restart_notice,
    write_restart_marker,
)


def test_set_and_consume_restart_notice_env_roundtrip(monkeypatch):
    monkeypatch.delenv("NANOBOT_RESTART_NOTIFY_CHANNEL", raising=False)
    monkeypatch.delenv("NANOBOT_RESTART_NOTIFY_CHAT_ID", raising=False)
    monkeypatch.delenv("NANOBOT_RESTART_STARTED_AT", raising=False)

    set_restart_notice_to_env(channel="feishu", chat_id="oc_123")

    notice = consume_restart_notice_from_env()
    assert notice is not None
    assert notice.channel == "feishu"
    assert notice.chat_id == "oc_123"
    assert notice.started_at_raw

    # Consumed values should be cleared from env.
    assert consume_restart_notice_from_env() is None
    assert "NANOBOT_RESTART_NOTIFY_CHANNEL" not in os.environ
    assert "NANOBOT_RESTART_NOTIFY_CHAT_ID" not in os.environ
    assert "NANOBOT_RESTART_STARTED_AT" not in os.environ


def test_format_restart_completed_message_with_elapsed(monkeypatch):
    monkeypatch.setattr("nanobot.utils.restart.time.time", lambda: 102.0)
    assert format_restart_completed_message("100.0") == "Restart completed in 2.0s."


def test_should_show_cli_restart_notice():
    notice = RestartNotice(channel="cli", chat_id="direct", started_at_raw="100")
    assert should_show_cli_restart_notice(notice, "cli:direct") is True
    assert should_show_cli_restart_notice(notice, "cli:other") is False
    assert should_show_cli_restart_notice(notice, "direct") is True

    non_cli = RestartNotice(channel="feishu", chat_id="oc_1", started_at_raw="100")
    assert should_show_cli_restart_notice(non_cli, "cli:direct") is False


def test_restart_marker_roundtrip(tmp_path):
    marker_path = tmp_path / "restart_marker.json"

    write_restart_marker("telegram self-heal exhausted", path=marker_path)

    marker = read_and_clear_restart_marker(path=marker_path)
    assert marker is not None
    assert marker.reason == "telegram self-heal exhausted"
    assert marker.started_at_raw
    assert not marker_path.exists()


def test_restart_cooldown_active_when_recent(tmp_path, monkeypatch):
    marker_path = tmp_path / "restart_marker.json"
    monkeypatch.setattr("nanobot.utils.restart.time.time", lambda: 200.0)
    write_restart_marker("test", path=marker_path)

    # 50s later — still within default 120s cooldown
    monkeypatch.setattr("nanobot.utils.restart.time.time", lambda: 250.0)
    assert is_restart_in_cooldown(path=marker_path) is True


def test_restart_cooldown_expired(tmp_path, monkeypatch):
    marker_path = tmp_path / "restart_marker.json"
    monkeypatch.setattr("nanobot.utils.restart.time.time", lambda: 200.0)
    write_restart_marker("test", path=marker_path)

    # 200s later — past 120s cooldown
    monkeypatch.setattr("nanobot.utils.restart.time.time", lambda: 400.0)
    assert is_restart_in_cooldown(path=marker_path) is False


def test_restart_cooldown_no_marker(tmp_path):
    marker_path = tmp_path / "restart_marker.json"
    assert is_restart_in_cooldown(path=marker_path) is False

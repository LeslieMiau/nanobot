"""Tests for gateway task supervisor and auto-recovery."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from nanobot.app.gateway import _TaskSupervisor


class TestTaskSupervisor:
    def test_initial_state(self):
        sup = _TaskSupervisor("test")
        assert sup.name == "test"
        assert sup.consecutive_failures == 0
        assert sup.backoff_s == _TaskSupervisor.INITIAL_BACKOFF_S
        assert not sup.should_escalate()

    def test_record_failure_increments(self):
        sup = _TaskSupervisor("test")
        sup.mark_started()
        sup.record_failure()
        assert sup.consecutive_failures == 1
        assert sup.backoff_s == 2.0

    def test_backoff_doubles_on_consecutive_failures(self):
        sup = _TaskSupervisor("test")
        for i in range(4):
            sup.mark_started()
            sup.record_failure()
        assert sup.consecutive_failures == 4
        assert sup.backoff_s == 16.0

    def test_backoff_caps_at_max(self):
        sup = _TaskSupervisor("test")
        for _ in range(10):
            sup.mark_started()
            sup.record_failure()
        assert sup.backoff_s == _TaskSupervisor.MAX_BACKOFF_S

    def test_escalate_after_max_failures(self):
        sup = _TaskSupervisor("test")
        for _ in range(_TaskSupervisor.MAX_CONSECUTIVE_FAILURES):
            sup.mark_started()
            sup.record_failure()
        assert sup.should_escalate()

    def test_no_escalate_before_max_failures(self):
        sup = _TaskSupervisor("test")
        for _ in range(_TaskSupervisor.MAX_CONSECUTIVE_FAILURES - 1):
            sup.mark_started()
            sup.record_failure()
        assert not sup.should_escalate()

    def test_healthy_run_resets_failure_count(self):
        sup = _TaskSupervisor("test")
        # Accumulate some failures
        for _ in range(3):
            sup.mark_started()
            sup.record_failure()
        assert sup.consecutive_failures == 3

        # Simulate a healthy run (>= MIN_HEALTHY_DURATION_S)
        sup.mark_started()
        with patch.object(time, "monotonic", return_value=sup._started_at + 31.0):
            sup.record_failure()
        assert sup.consecutive_failures == 1
        assert sup.backoff_s == _TaskSupervisor.INITIAL_BACKOFF_S

    def test_short_run_does_not_reset(self):
        sup = _TaskSupervisor("test")
        sup.mark_started()
        sup.record_failure()
        assert sup.consecutive_failures == 1

        # Simulate a short run (< MIN_HEALTHY_DURATION_S)
        sup.mark_started()
        with patch.object(time, "monotonic", return_value=sup._started_at + 5.0):
            sup.record_failure()
        assert sup.consecutive_failures == 2

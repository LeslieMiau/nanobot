import asyncio
from pathlib import Path

import pytest

from nanobot.repo_sync.service import RepoSyncWatcher, sync_fork_once


@pytest.mark.asyncio
async def test_repo_sync_watcher_runs_immediately_on_start() -> None:
    calls: list[dict] = []

    async def _fake_sync(**kwargs) -> str:
        calls.append(kwargs)
        return "Repo sync: already up to date."

    watcher = RepoSyncWatcher(
        repo_path=".",
        interval_s=3600,
        run_on_start=True,
        sync_runner=_fake_sync,
    )

    await watcher.start()
    watcher.stop()

    assert len(calls) == 1
    assert calls[0]["repo_path"] == "."


@pytest.mark.asyncio
async def test_repo_sync_watcher_polls_while_running() -> None:
    calls: list[dict] = []

    async def _fake_sync(**kwargs) -> str:
        calls.append(kwargs)
        return "Repo sync: already up to date."

    watcher = RepoSyncWatcher(
        repo_path=".",
        interval_s=0.05,
        sync_hour=-1,
        run_on_start=False,
        sync_runner=_fake_sync,
    )

    await watcher.start()
    try:
        await asyncio.sleep(0.14)
    finally:
        watcher.stop()

    assert len(calls) >= 2


@pytest.mark.asyncio
async def test_repo_sync_watcher_start_is_idempotent() -> None:
    calls: list[dict] = []

    async def _fake_sync(**kwargs) -> str:
        calls.append(kwargs)
        return "Repo sync: already up to date."

    watcher = RepoSyncWatcher(
        repo_path=".",
        interval_s=3600,
        run_on_start=True,
        sync_runner=_fake_sync,
    )

    await watcher.start()
    await watcher.start()
    watcher.stop()

    assert len(calls) == 1


@pytest.mark.asyncio
async def test_repo_sync_watcher_stop_is_idempotent_and_clears_task() -> None:
    async def _fake_sync(**kwargs) -> str:
        return "Repo sync: already up to date."

    watcher = RepoSyncWatcher(
        repo_path=".",
        interval_s=3600,
        run_on_start=False,
        sync_runner=_fake_sync,
    )

    await watcher.start()
    watcher.stop()
    watcher.stop()

    assert watcher._task is None
    assert watcher._running is False


@pytest.mark.asyncio
async def test_repo_sync_watcher_trigger_now_serializes_calls() -> None:
    active = 0
    max_active = 0
    calls: list[str] = []

    async def _fake_sync(**kwargs) -> str:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        calls.append(kwargs["repo_path"])
        await asyncio.sleep(0.02)
        active -= 1
        return "Repo sync: already up to date."

    watcher = RepoSyncWatcher(
        repo_path=".",
        run_on_start=False,
        sync_runner=_fake_sync,
    )

    await asyncio.gather(watcher.trigger_now(), watcher.trigger_now())

    assert calls == [".", "."]
    assert max_active == 1


@pytest.mark.asyncio
async def test_sync_fork_once_reports_missing_repo_path(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing-repo"

    result = await sync_fork_once(repo_path=missing_path)

    assert "Repo sync failed" in result
    assert str(missing_path) in result

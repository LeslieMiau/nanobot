import asyncio

import pytest

from nanobot.repo_sync.service import RepoSyncWatcher


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

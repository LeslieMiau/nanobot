from __future__ import annotations

import time

from nanobot.coding_tasks.manager import CodexWorkerManager
from nanobot.coding_tasks.policy import CodingTaskPolicy
from nanobot.coding_tasks.store import CodingTaskStore


def test_policy_preserves_workspace_single_active_selection(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    first = manager.create_task(
        repo_path=str(repo_a),
        goal="First",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-a"},
    )
    second = manager.create_task(
        repo_path=str(repo_b),
        goal="Second",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-b"},
    )
    time.sleep(0.01)
    manager.mark_starting(second.id, summary="Boot")

    policy = CodingTaskPolicy(manager)

    assert policy.blocking_active_task() is not None
    assert policy.blocking_active_task().id == second.id
    assert first.id != second.id


def test_policy_preserves_origin_chat_task_selection(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()

    older = manager.create_task(
        repo_path=str(repo_a),
        goal="Older",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-a"},
    )
    manager.mark_starting(older.id, summary="Boot")
    manager.mark_waiting_user(older.id, summary="Waiting")
    newer = manager.create_task(
        repo_path=str(repo_b),
        goal="Newer",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-a"},
    )
    time.sleep(0.01)
    manager.mark_starting(newer.id, summary="Boot")
    manager.mark_running(newer.id, summary="Working")

    policy = CodingTaskPolicy(manager)

    assert policy.latest_origin_task("telegram", "chat-a") is not None
    assert policy.latest_origin_task("telegram", "chat-a").id == newer.id
    assert policy.select_control_task("telegram", "chat-a") is not None
    assert policy.select_control_task("telegram", "chat-a").id == newer.id


def test_policy_hides_terminal_tasks_from_visible_origin_list(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo = tmp_path / "repo"
    repo.mkdir()

    completed = manager.create_task(
        repo_path=str(repo),
        goal="Completed",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-a"},
    )
    manager.mark_starting(completed.id, summary="Boot")
    manager.mark_completed(completed.id, summary="Done")

    failed = manager.create_task(
        repo_path=str(repo),
        goal="Failed",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-a"},
    )
    manager.mark_starting(failed.id, summary="Boot")
    manager.mark_failed(failed.id, summary="Oops")

    cancelled = manager.create_task(
        repo_path=str(repo),
        goal="Cancelled",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-a"},
    )
    manager.mark_starting(cancelled.id, summary="Boot")
    manager.cancel_task(cancelled.id, summary="Stop")

    policy = CodingTaskPolicy(manager)

    tasks = policy.tasks_for_origin("telegram", "chat-a")

    assert tasks == []
    assert policy.task_for_origin_index("telegram", "chat-a", 1) is None
    assert policy.task_for_origin_index("telegram", "chat-a", 2) is None


def test_policy_visible_tasks_can_include_terminal_history(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo = tmp_path / "repo"
    repo.mkdir()

    queued = manager.create_task(repo_path=str(repo), goal="Queued")
    completed = manager.create_task(repo_path=str(repo), goal="Completed")
    manager.mark_starting(completed.id, summary="Boot")
    manager.mark_completed(completed.id, summary="Done")

    policy = CodingTaskPolicy(manager)

    assert [task.id for task in policy.visible_tasks()] == [queued.id]
    assert {task.id for task in policy.visible_tasks(include_terminal=True)} == {queued.id, completed.id}


def test_policy_does_not_block_new_tasks_on_worker_exit_review_wait(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo = tmp_path / "repo"
    repo.mkdir()

    review = manager.create_task(
        repo_path=str(repo),
        goal="Review result",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-a"},
    )
    manager.mark_starting(review.id, summary="Boot")
    manager.mark_waiting_user(review.id, summary="Review result")
    manager.update_metadata(
        review.id,
        updates={"waiting_reason_kind": "worker_exit_review"},
    )

    policy = CodingTaskPolicy(manager)

    assert policy.blocking_active_task() is None
    assert policy.select_control_task("telegram", "chat-a") is not None
    assert policy.select_control_task("telegram", "chat-a").id == review.id


def test_policy_clears_stale_harness_conflict_from_blocking_selection(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    repo = tmp_path / "repo"
    repo.mkdir()

    stale = manager.create_task(
        repo_path=str(repo),
        goal="Resume old harness",
        metadata={
            "origin_channel": "telegram",
            "origin_chat_id": "chat-a",
            "harness_conflict_reason": "repo_active_harness",
            "harness_conflict_resolution": "resume_existing",
        },
    )
    manager.mark_starting(stale.id, summary="Boot")
    manager.mark_waiting_user(stale.id, summary="Waiting for old harness choice")

    policy = CodingTaskPolicy(manager)

    assert policy.blocking_active_task() is None
    updated = store.get_task(stale.id)
    assert updated is not None
    assert updated.status == "cancelled"
    assert "Cleared stale harness conflict record" in updated.last_progress_summary


def test_policy_hides_stale_harness_conflict_from_origin_task_list(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    manager = CodexWorkerManager(tmp_path, store)
    stale_repo = tmp_path / "stale-repo"
    stale_repo.mkdir()
    valid_repo = tmp_path / "valid-repo"
    valid_repo.mkdir()

    valid = manager.create_task(
        repo_path=str(valid_repo),
        goal="Completed",
        metadata={"origin_channel": "telegram", "origin_chat_id": "chat-a"},
    )
    manager.mark_starting(valid.id, summary="Boot")
    manager.mark_completed(valid.id, summary="Done")

    stale = manager.create_task(
        repo_path=str(stale_repo),
        goal="Resume old harness",
        metadata={
            "origin_channel": "telegram",
            "origin_chat_id": "chat-a",
            "harness_conflict_reason": "repo_active_harness",
            "harness_conflict_resolution": "resume_existing",
        },
    )
    manager.mark_starting(stale.id, summary="Boot")
    manager.mark_waiting_user(stale.id, summary="Waiting for old harness choice")

    policy = CodingTaskPolicy(manager)

    tasks = policy.tasks_for_origin("telegram", "chat-a")

    assert tasks == []
    updated = store.get_task(stale.id)
    assert updated is not None
    assert updated.status == "cancelled"

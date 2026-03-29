import json

from nanobot.coding_tasks.store import CodingTaskStore
from nanobot.coding_tasks.types import CodingRunEvent, CodingTask


def test_upsert_task_persists_to_disk(tmp_path) -> None:
    store_path = tmp_path / "automation" / "coding" / "tasks.json"
    store = CodingTaskStore(store_path)

    task = CodingTask(
        id="task-1",
        title="repo task",
        repo_path="/tmp/repo",
        goal="Implement feature",
    )
    store.upsert_task(task)

    loaded = store.get_task("task-1")
    assert loaded is not None
    assert loaded.goal == "Implement feature"

    raw = json.loads(store_path.read_text(encoding="utf-8"))
    assert raw["version"] == CodingTaskStore.VERSION
    assert raw["tasks"][0]["id"] == "task-1"


def test_append_run_event_round_trips_jsonl(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")

    store.append_run_event(
        CodingRunEvent(
            task_id="task-1",
            event="created",
            status="queued",
            message="start task",
            payload={"repo_path": "/tmp/repo"},
        )
    )
    store.append_run_event(
        CodingRunEvent(
            task_id="task-1",
            event="status_changed",
            status="running",
            message="booted codex",
        )
    )

    events = store.read_run_events("task-1")
    assert [event.event for event in events] == ["created", "status_changed"]
    assert events[0].payload["repo_path"] == "/tmp/repo"


def test_list_tasks_by_status_filters_results(tmp_path) -> None:
    store = CodingTaskStore(tmp_path / "automation" / "coding" / "tasks.json")
    store.upsert_task(
        CodingTask(
            id="queued",
            title="queued",
            repo_path="/tmp/repo-a",
            goal="A",
            status="queued",
        )
    )
    store.upsert_task(
        CodingTask(
            id="running",
            title="running",
            repo_path="/tmp/repo-b",
            goal="B",
            status="running",
        )
    )

    recoverable = store.list_tasks_by_status("running", "waiting_user")
    assert [task.id for task in recoverable] == ["running"]

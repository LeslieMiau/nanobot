"""Workspace-backed persistence for coding tasks."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from nanobot.coding_tasks.types import CodingRunEvent, CodingTask
from nanobot.utils.helpers import ensure_dir


class CodingTaskStore:
    """Persist coding tasks and append-only run logs under the workspace."""

    VERSION = 1

    def __init__(self, store_path: Path):
        self.store_path = store_path
        self.base_dir = store_path.parent
        self.runs_dir = self.base_dir / "runs"
        ensure_dir(self.base_dir)
        ensure_dir(self.runs_dir)

    def _load_raw(self) -> dict:
        if not self.store_path.exists():
            return {"version": self.VERSION, "tasks": []}
        return json.loads(self.store_path.read_text(encoding="utf-8"))

    def _save_tasks(self, tasks: list[CodingTask]) -> None:
        payload = {
            "version": self.VERSION,
            "tasks": [asdict(task) for task in tasks],
        }
        self.store_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def list_tasks(self) -> list[CodingTask]:
        raw = self._load_raw()
        return [CodingTask(**item) for item in raw.get("tasks", [])]

    def get_task(self, task_id: str) -> CodingTask | None:
        for task in self.list_tasks():
            if task.id == task_id:
                return task
        return None

    def upsert_task(self, task: CodingTask) -> CodingTask:
        tasks = self.list_tasks()
        for idx, existing in enumerate(tasks):
            if existing.id == task.id:
                tasks[idx] = task
                self._save_tasks(tasks)
                return task
        tasks.append(task)
        self._save_tasks(tasks)
        return task

    def list_tasks_by_status(self, *statuses: str) -> list[CodingTask]:
        wanted = set(statuses)
        return [task for task in self.list_tasks() if task.status in wanted]

    def append_run_event(self, event: CodingRunEvent) -> CodingRunEvent:
        path = self.runs_dir / f"{event.task_id}.jsonl"
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")
        return event

    def read_run_events(self, task_id: str, limit: int | None = None) -> list[CodingRunEvent]:
        path = self.runs_dir / f"{task_id}.jsonl"
        if not path.exists():
            return []

        events: list[CodingRunEvent] = []
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                events.append(CodingRunEvent(**json.loads(line)))
        if limit is None or limit >= len(events):
            return events
        return events[-limit:]

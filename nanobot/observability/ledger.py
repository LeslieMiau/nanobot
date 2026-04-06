"""Append-only JSONL cost ledger for LLM usage tracking."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from loguru import logger


class CostLedger:
    """Persistent cost ledger backed by a JSONL file."""

    def __init__(self, workspace: Path) -> None:
        self._dir = workspace / "observability"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "cost_ledger.jsonl"

    def log(
        self,
        *,
        model: str,
        provider: str,
        prompt_tokens: int,
        completion_tokens: int,
        cost_usd: float | None,
        session_key: str = "",
        cached_tokens: int = 0,
        duration_ms: int = 0,
    ) -> None:
        """Append a single usage entry to the ledger."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "model": model,
            "provider": provider,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cached_tokens": cached_tokens,
            "cost_usd": round(cost_usd, 6) if cost_usd is not None else None,
            "session_key": session_key,
            "duration_ms": duration_ms,
        }
        try:
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("Failed to write cost ledger entry: {}", exc)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def _load(self, start: datetime | None = None, end: datetime | None = None) -> list[dict[str, Any]]:
        """Load ledger entries, optionally filtered by time range."""
        if not self._path.exists():
            return []
        entries: list[dict[str, Any]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if start or end:
                try:
                    ts = datetime.fromisoformat(entry["ts"])
                except (KeyError, ValueError):
                    continue
                if start and ts < start:
                    continue
                if end and ts > end:
                    continue
            entries.append(entry)
        return entries

    @staticmethod
    def _period_range(period: str) -> tuple[datetime | None, datetime | None]:
        """Convert period name to (start, end) datetimes."""
        now = datetime.now(timezone.utc)
        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "month":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif period == "all":
            return None, None
        else:
            return None, None
        return start, None

    def get_period_cost(self, period: str = "month") -> float:
        """Return total USD cost for the given period."""
        start, end = self._period_range(period)
        return sum(e.get("cost_usd") or 0.0 for e in self._load(start, end))

    def query(
        self,
        period: str = "all",
        group_by: str | None = None,
    ) -> list[dict[str, Any]]:
        """Aggregate ledger entries by optional dimension.

        Returns a list of dicts with keys: group, total_cost, prompt_tokens,
        completion_tokens, count.
        """
        start, end = self._period_range(period)
        entries = self._load(start, end)

        if group_by is None:
            total = _aggregate(entries)
            total["group"] = "total"
            return [total]

        buckets: dict[str, list[dict]] = {}
        for e in entries:
            if group_by == "model":
                key = e.get("model", "unknown")
            elif group_by == "session":
                key = e.get("session_key", "unknown")
            elif group_by == "channel":
                sk = e.get("session_key", "")
                key = sk.split(":", 1)[0] if ":" in sk else sk or "unknown"
            elif group_by == "day":
                try:
                    key = datetime.fromisoformat(e["ts"]).strftime("%Y-%m-%d")
                except (KeyError, ValueError):
                    key = "unknown"
            else:
                key = "total"
            buckets.setdefault(key, []).append(e)

        results = []
        for key, items in sorted(buckets.items()):
            row = _aggregate(items)
            row["group"] = key
            results.append(row)
        return results

    def summary(self) -> dict[str, float]:
        """Quick summary: today / this week / this month costs."""
        return {
            "today": self.get_period_cost("today"),
            "week": self.get_period_cost("week"),
            "month": self.get_period_cost("month"),
        }


def _aggregate(entries: list[dict]) -> dict[str, Any]:
    """Aggregate a list of ledger entries into summary stats."""
    return {
        "total_cost": round(sum(e.get("cost_usd") or 0.0 for e in entries), 4),
        "prompt_tokens": sum(e.get("prompt_tokens", 0) for e in entries),
        "completion_tokens": sum(e.get("completion_tokens", 0) for e in entries),
        "cached_tokens": sum(e.get("cached_tokens", 0) for e in entries),
        "count": len(entries),
    }

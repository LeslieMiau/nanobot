#!/usr/bin/env python3
"""Collect weekly activity data from nanobot workspace for review generation.

Usage:
    python collect_data.py --workspace ~/.nanobot/workspace --days 7
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

_TS_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]")
_TOOLS_RE = re.compile(r"\[tools: ([^\]]+)\]")


def parse_history(workspace: Path, cutoff: datetime) -> tuple[list[dict], Counter]:
    """Parse HISTORY.md and return entries within the date range + tool counts."""
    history_file = workspace / "memory" / "HISTORY.md"
    if not history_file.exists():
        return [], Counter()

    entries: list[dict] = []
    tools: Counter = Counter()
    current_entry: dict | None = None

    for line in history_file.read_text(encoding="utf-8").splitlines():
        m = _TS_RE.match(line)
        if m:
            if current_entry:
                entries.append(current_entry)
            try:
                ts = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
            except ValueError:
                current_entry = None
                continue
            if ts < cutoff:
                current_entry = None
                continue

            # Extract tools
            tm = _TOOLS_RE.search(line)
            if tm:
                for t in tm.group(1).split(", "):
                    tools[t.strip()] += 1

            rest = _TS_RE.sub("", line).strip()
            current_entry = {
                "timestamp": m.group(1),
                "content": rest,
            }
        elif current_entry:
            current_entry["content"] += "\n" + line

    if current_entry:
        entries.append(current_entry)

    return entries, tools


def scan_sessions(workspace: Path, cutoff: datetime) -> dict:
    """Scan session JSONL files for activity within the date range."""
    sessions_dir = workspace / "sessions"
    if not sessions_dir.exists():
        return {"total_sessions": 0, "total_messages": 0, "active_channels": [], "sessions": []}

    active_sessions: list[dict] = []
    channels: set[str] = set()
    total_messages = 0

    for f in sessions_dir.glob("*.jsonl"):
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        if not lines:
            continue

        # Count messages with timestamps in range
        msg_count = 0
        last_active = ""
        for raw in lines:
            raw = raw.strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            ts_str = msg.get("timestamp", msg.get("ts", ""))
            if not ts_str:
                msg_count += 1  # count anyway if no timestamp
                continue
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).replace(tzinfo=None)
            except (ValueError, TypeError):
                msg_count += 1
                continue
            if ts >= cutoff:
                msg_count += 1
                last_active = ts_str

        if msg_count > 0:
            session_key = f.stem
            if ":" in session_key:
                channels.add(session_key.split(":", 1)[0])
            active_sessions.append({
                "key": session_key,
                "message_count": msg_count,
                "last_active": last_active,
            })
            total_messages += msg_count

    return {
        "total_sessions": len(active_sessions),
        "total_messages": total_messages,
        "active_channels": sorted(channels),
        "sessions": sorted(active_sessions, key=lambda s: s["message_count"], reverse=True),
    }


def scan_cost_ledger(workspace: Path, cutoff: datetime) -> dict:
    """Scan cost ledger for the period."""
    ledger_file = workspace / "observability" / "cost_ledger.jsonl"
    if not ledger_file.exists():
        return {"total_cost": 0.0, "total_calls": 0, "by_model": {}}

    total_cost = 0.0
    total_calls = 0
    by_model: Counter = Counter()

    for line in ledger_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            ts = datetime.fromisoformat(entry["ts"].replace("Z", "+00:00")).replace(tzinfo=None)
        except (KeyError, ValueError):
            continue
        if ts < cutoff:
            continue
        cost = entry.get("cost_usd") or 0.0
        total_cost += cost
        total_calls += 1
        by_model[entry.get("model", "unknown")] += cost

    return {
        "total_cost": round(total_cost, 4),
        "total_calls": total_calls,
        "by_model": {k: round(v, 4) for k, v in by_model.most_common()},
    }


def main():
    parser = argparse.ArgumentParser(description="Collect nanobot weekly review data")
    parser.add_argument("--workspace", required=True, help="Workspace path")
    parser.add_argument("--days", type=int, default=7, help="Number of days to look back")
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser()
    cutoff = datetime.now() - timedelta(days=args.days)

    history_entries, tools_used = parse_history(workspace, cutoff)
    session_stats = scan_sessions(workspace, cutoff)
    cost_stats = scan_cost_ledger(workspace, cutoff)

    result = {
        "period": {
            "start": cutoff.strftime("%Y-%m-%d"),
            "end": datetime.now().strftime("%Y-%m-%d"),
            "days": args.days,
        },
        "history_entries": history_entries,
        "history_entry_count": len(history_entries),
        "session_stats": session_stats,
        "tools_used": dict(tools_used.most_common()),
        "cost_stats": cost_stats,
    }

    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

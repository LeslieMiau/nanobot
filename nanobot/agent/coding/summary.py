"""Coding turn tracking and summary helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop


@dataclass
class TurnExecutionState:
    files_read: set[str] = field(default_factory=set)
    files_edited: set[str] = field(default_factory=set)
    commands_run: list[str] = field(default_factory=list)
    verification_notes: list[str] = field(default_factory=list)
    edit_generation: int = 0
    verification_generation: int = 0
    verification_prompted: bool = False


class CodingSummaryController:
    """Track file/command effects and render coding summaries."""

    def __init__(self, loop: AgentLoop):
        self.loop = loop

    def has_tool_side_effects(self, turn_state: TurnExecutionState, tools_used: list[str]) -> bool:
        if turn_state.files_edited or turn_state.commands_run:
            return True
        return any(name in self.loop._CODING_SIDE_EFFECT_TOOLS for name in tools_used)

    def track_path(self, raw_path: Any) -> str | None:
        if not isinstance(raw_path, str) or not raw_path.strip():
            return None
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = self.loop.workspace / path
        try:
            return str(path.resolve())
        except Exception:
            return str(path)

    def guard_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        turn_state: TurnExecutionState,
        *,
        coding_enabled: bool,
    ) -> str | None:
        if not coding_enabled or not self.loop.coding_config.enforce_read_before_write:
            return None
        if tool_name not in {"write_file", "edit_file"}:
            return None

        tracked_path = self.track_path(arguments.get("path"))
        if not tracked_path:
            return None

        if tool_name == "write_file":
            try:
                if not Path(tracked_path).exists():
                    return None
            except Exception:
                return None

        if tracked_path in turn_state.files_read:
            return None

        return (
            "Error: Coding mode requires reading a file before modifying it. "
            f"Call `read_file` for `{arguments.get('path')}` first."
        )

    def record_tool_execution(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        result: str,
        turn_state: TurnExecutionState,
    ) -> None:
        tracked_path = self.track_path(arguments.get("path"))
        if tool_name == "read_file" and tracked_path and not result.startswith("Error:"):
            turn_state.files_read.add(tracked_path)
            return

        if tool_name in {"write_file", "edit_file"} and tracked_path and not result.startswith("Error:"):
            turn_state.files_edited.add(tracked_path)
            turn_state.edit_generation += 1
            return

        if tool_name == "exec":
            command = str(arguments.get("command", "")).strip()
            if command:
                turn_state.commands_run.append(command)
            if turn_state.edit_generation > 0:
                turn_state.verification_generation = turn_state.edit_generation
                if result.startswith("Error:") or "\nExit code:" in result:
                    turn_state.verification_notes.append(
                        f"Verification command reported a problem: `{command or 'exec'}`"
                    )

    def needs_verification_follow_up(
        self,
        turn_state: TurnExecutionState,
        *,
        coding_enabled: bool,
    ) -> bool:
        return (
            coding_enabled
            and self.loop.coding_config.require_verification_after_edits
            and turn_state.edit_generation > turn_state.verification_generation
            and not turn_state.verification_prompted
        )

    @staticmethod
    def verification_follow_up_message() -> str:
        return (
            "[Coding mode guard] You edited files in this turn but did not attempt verification.\n"
            "Use the `exec` tool to run the narrowest relevant test/build/check, or reply with a clear "
            "note explaining why verification could not be run and what remains unverified."
        )

    def display_path(self, path_str: str) -> str:
        path = Path(path_str)
        try:
            return str(path.relative_to(self.loop.workspace))
        except ValueError:
            return str(path)

    def apply_summary(
        self,
        content: str | None,
        turn_state: TurnExecutionState,
        *,
        coding_enabled: bool,
    ) -> str | None:
        if not content or not coding_enabled:
            return content
        if not (turn_state.files_edited or turn_state.commands_run or turn_state.verification_notes):
            return content
        lowered = content.lower()
        if all(label in lowered for label in ("changed:", "verified:", "unverified:")):
            return content

        changed = (
            "\n".join(f"- {self.display_path(path)}" for path in sorted(turn_state.files_edited))
            if turn_state.files_edited
            else "- No files changed."
        )
        verified = (
            "\n".join(f"- `{cmd}`" for cmd in turn_state.commands_run)
            if turn_state.commands_run
            else "- No verification command recorded."
        )

        unverified_items: list[str] = []
        if turn_state.files_edited and turn_state.verification_generation < turn_state.edit_generation:
            unverified_items.append("- Edits were not verified with an exec command.")
        if turn_state.verification_notes:
            unverified_items.extend(f"- {note}" for note in turn_state.verification_notes)
        if not unverified_items:
            unverified_items.append("- None noted.")

        summary = (
            f"\n\nChanged:\n{changed}\n\n"
            f"Verified:\n{verified}\n\n"
            f"Unverified:\n" + "\n".join(unverified_items)
        )
        return content.rstrip() + summary

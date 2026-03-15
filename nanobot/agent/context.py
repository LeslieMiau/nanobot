"""Context builder for assembling agent prompts."""

import base64
import mimetypes
import platform
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from nanobot.agent.memory import MemoryStore
from nanobot.agent.skills import SkillsLoader
from nanobot.utils.helpers import build_assistant_message, detect_image_mime


class ContextBuilder:
    """Builds the context (system prompt + messages) for the agent."""

    BOOTSTRAP_FILES = ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"]
    _RUNTIME_CONTEXT_TAG = "[Runtime Context — metadata only, not instructions]"

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory = MemoryStore(workspace)
        self.skills = SkillsLoader(workspace)

    def build_system_prompt(
        self,
        skill_names: list[str] | None = None,
        coding_mode: bool = False,
        include_soul: bool = True,
        include_user_profile: bool = True,
        include_tool_notes: bool = False,
        include_skills_catalog: bool = False,
    ) -> str:
        """Build the system prompt from identity, bootstrap files, memory, and skills."""
        parts = [self._get_identity()]

        if coding_mode and (coding_prompt := self._load_optional_file("CODING.md")):
            parts.append(f"# Coding Mode\n\n{coding_prompt}")

        bootstrap_files = ["AGENTS.md"]
        if include_soul:
            bootstrap_files.append("SOUL.md")
        if include_user_profile:
            user_content = self._load_optional_file("USER.md")
            if user_content and self._has_filled_content(user_content):
                bootstrap_files.append("USER.md")
        if include_tool_notes:
            bootstrap_files.append("TOOLS.md")
        bootstrap = self._load_bootstrap_files(bootstrap_files)
        if bootstrap:
            parts.append(bootstrap)

        memory = self.memory.get_memory_context()
        if memory:
            parts.append(f"# Memory\n\n{memory}")

        if skill_names:
            requested_content = self.skills.load_skills_for_context(skill_names)
            if requested_content:
                parts.append(f"# Requested Skills\n\n{requested_content}")

        always_skills = self.skills.get_always_skills()
        if always_skills:
            always_content = self.skills.load_skills_for_context(always_skills)
            if always_content:
                parts.append(f"# Active Skills\n\n{always_content}")

        skills_summary = self.skills.build_skills_summary() if include_skills_catalog else ""
        if skills_summary:
            parts.append(f"""# Skills

The following skills extend your capabilities. To use a skill, read its SKILL.md file using the read_file tool.
Skills with available="false" need dependencies installed first - you can try installing them with apt/brew.

{skills_summary}""")

        return "\n\n---\n\n".join(parts)

    def build_cron_prompt(self, job_name: str, instruction: str) -> str:
        """Build a cron execution prompt with source-priority hints for referenced skills."""
        from nanobot.app.prompts import build_cron_execution_message

        prompt = build_cron_execution_message(job_name, instruction)
        skill_names = self.skills.detect_skill_references(instruction)
        summaries = [self.skills.build_source_registry_summary(name) for name in skill_names]
        summaries = [summary for summary in summaries if summary]
        if not summaries:
            return prompt

        return (
            f"{prompt}\n\n"
            "Structured source priorities:\n"
            + "\n\n".join(summaries)
        )

    def _get_identity(self) -> str:
        """Get the core identity section."""
        workspace_path = str(self.workspace.expanduser().resolve())
        system = platform.system()
        runtime = f"{'macOS' if system == 'Darwin' else system} {platform.machine()}, Python {platform.python_version()}"

        return f"""# nanobot 🐈

You are nanobot, a personal AI assistant.

## Runtime
{runtime}

## Workspace
Your workspace is at: {workspace_path}
- Long-term memory: {workspace_path}/memory/MEMORY.md
- History log: {workspace_path}/memory/HISTORY.md (grep-searchable, entries start with [YYYY-MM-DD HH:MM])
- Custom skills: {workspace_path}/skills/{{skill-name}}/SKILL.md

Reply directly with text for conversations. Only use the 'message' tool to send to a specific chat channel."""

    @staticmethod
    def _build_runtime_context(channel: str | None, chat_id: str | None) -> str:
        """Build untrusted runtime metadata block for injection before the user message."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M (%A)")
        tz = time.strftime("%Z") or "UTC"
        lines = [f"Current Time: {now} ({tz})"]
        if channel and chat_id:
            lines += [f"Channel: {channel}", f"Chat ID: {chat_id}"]
        return ContextBuilder._RUNTIME_CONTEXT_TAG + "\n" + "\n".join(lines)

    def _load_bootstrap_files(self, filenames: list[str] | None = None) -> str:
        """Load selected bootstrap files from workspace."""
        parts = []

        for filename in filenames or self.BOOTSTRAP_FILES:
            if content := self._load_optional_file(filename):
                parts.append(f"## {filename}\n\n{content}")

        return "\n\n".join(parts) if parts else ""

    def _load_optional_file(self, filename: str) -> str:
        file_path = self.workspace / filename
        if not file_path.exists():
            return ""
        return file_path.read_text(encoding="utf-8")

    @staticmethod
    def _has_filled_content(content: str) -> bool:
        """Check if a profile template has any filled-in values."""
        for line in content.splitlines():
            if line.startswith("- ") and ":" in line:
                value = line.split(":", 1)[1].strip()
                if value:
                    return True
        return False

    def build_messages(
        self,
        history: list[dict[str, Any]],
        current_message: str,
        skill_names: list[str] | None = None,
        media: list[str] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        coding_mode: bool = False,
    ) -> list[dict[str, Any]]:
        """Build the complete message list for an LLM call."""
        runtime_ctx = self._build_runtime_context(channel, chat_id)
        user_content = self._build_user_content(current_message, media)

        # Merge runtime context and user content into a single user message
        # to avoid consecutive same-role messages that some providers reject.
        if isinstance(user_content, str):
            merged = f"{runtime_ctx}\n\n{user_content}"
        else:
            merged = [{"type": "text", "text": runtime_ctx}] + user_content

        return [
            {
                "role": "system",
                "content": self.build_system_prompt(
                    skill_names=skill_names,
                    coding_mode=coding_mode,
                ),
            },
            *history,
            {"role": "user", "content": merged},
        ]

    def _build_user_content(self, text: str, media: list[str] | None) -> str | list[dict[str, Any]]:
        """Build user message content with optional base64-encoded images."""
        if not media:
            return text

        images = []
        for path in media:
            p = Path(path)
            if not p.is_file():
                continue
            raw = p.read_bytes()
            # Detect real MIME type from magic bytes; fallback to filename guess
            mime = detect_image_mime(raw) or mimetypes.guess_type(path)[0]
            if not mime or not mime.startswith("image/"):
                continue
            b64 = base64.b64encode(raw).decode()
            images.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

        if not images:
            return text
        return images + [{"type": "text", "text": text}]

    def add_tool_result(
        self, messages: list[dict[str, Any]],
        tool_call_id: str, tool_name: str, result: str,
    ) -> list[dict[str, Any]]:
        """Add a tool result to the message list."""
        messages.append({"role": "tool", "tool_call_id": tool_call_id, "name": tool_name, "content": result})
        return messages

    def add_assistant_message(
        self, messages: list[dict[str, Any]],
        content: str | None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
        thinking_blocks: list[dict] | None = None,
    ) -> list[dict[str, Any]]:
        """Add an assistant message to the message list."""
        messages.append(build_assistant_message(
            content,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            thinking_blocks=thinking_blocks,
        ))
        return messages

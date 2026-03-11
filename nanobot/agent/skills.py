"""Skills loader for agent capabilities."""

from dataclasses import dataclass
import json
import os
import re
import shutil
from pathlib import Path

# Default builtin skills directory (relative to this file)
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"


@dataclass(frozen=True)
class SkillSourceEntry:
    """Structured source-registry entry extracted from a skill reference file."""

    tier: str
    source: str
    label: str
    url: str
    priority: str


class SkillsLoader:
    """
    Loader for agent skills.

    Skills are markdown files (SKILL.md) that teach the agent how to use
    specific tools or perform certain tasks.
    """

    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None):
        self.workspace = workspace
        self.workspace_skills = workspace / "skills"
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR

    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        """
        List all available skills.

        Args:
            filter_unavailable: If True, filter out skills with unmet requirements.

        Returns:
            List of skill info dicts with 'name', 'path', 'source'.
        """
        skills = []

        # Workspace skills (highest priority)
        if self.workspace_skills.exists():
            for skill_dir in self.workspace_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "workspace"})

        # Built-in skills
        if self.builtin_skills and self.builtin_skills.exists():
            for skill_dir in self.builtin_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists() and not any(s["name"] == skill_dir.name for s in skills):
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "builtin"})

        # Filter by requirements
        if filter_unavailable:
            return [s for s in skills if self._check_requirements(self._get_skill_meta(s["name"]))]
        return skills

    def load_skill(self, name: str) -> str | None:
        """
        Load a skill by name.

        Args:
            name: Skill name (directory name).

        Returns:
            Skill content or None if not found.
        """
        # Check workspace first
        workspace_skill = self.workspace_skills / name / "SKILL.md"
        if workspace_skill.exists():
            return workspace_skill.read_text(encoding="utf-8")

        # Check built-in
        if self.builtin_skills:
            builtin_skill = self.builtin_skills / name / "SKILL.md"
            if builtin_skill.exists():
                return builtin_skill.read_text(encoding="utf-8")

        return None

    def load_skill_reference(self, name: str, relative_path: str) -> str | None:
        """Load a file relative to a skill directory."""
        skill_dir = self._resolve_skill_dir(name)
        if not skill_dir:
            return None
        ref_path = skill_dir / relative_path
        if not ref_path.exists() or not ref_path.is_file():
            return None
        return ref_path.read_text(encoding="utf-8")

    def load_source_registry(
        self,
        name: str,
        relative_path: str = "references/sources.md",
    ) -> list[SkillSourceEntry]:
        """Parse a skill's source registry into structured prioritized entries."""
        raw = self.load_skill_reference(name, relative_path)
        if not raw:
            return []

        tier = ""
        source = ""
        entries: list[SkillSourceEntry] = []
        for line in raw.splitlines():
            stripped = line.strip()
            if stripped.startswith("## "):
                tier = stripped[3:].strip()
                source = ""
                continue
            if stripped.startswith("### "):
                source = stripped[4:].strip()
                continue

            match = re.match(r"^- ([^:]+):\s+(https?://\S+)$", stripped)
            if not match or not tier or not source:
                continue

            label = match.group(1).strip()
            url = match.group(2).strip().rstrip(")")
            entries.append(
                SkillSourceEntry(
                    tier=tier,
                    source=source,
                    label=label,
                    url=url,
                    priority=self._classify_source_priority(label, url),
                )
            )

        return entries

    def build_source_registry_summary(
        self,
        name: str,
        relative_path: str = "references/sources.md",
    ) -> str:
        """Build a compact priority-ordered source summary for prompts."""
        entries = self.load_source_registry(name, relative_path)
        if not entries:
            return ""

        grouped: dict[str, list[SkillSourceEntry]] = {
            "primary": [],
            "fallback": [],
            "signal-only": [],
        }
        for entry in entries:
            grouped.setdefault(entry.priority, []).append(entry)

        lines = [
            f"Skill: {name}",
            "Priority order: primary -> fallback -> signal-only",
        ]
        for priority in ("primary", "fallback", "signal-only"):
            if not grouped.get(priority):
                continue
            lines.append(f"{priority}:")
            for entry in grouped[priority]:
                lines.append(
                    f"- {entry.source} | {entry.label} | {entry.priority} | {entry.url}"
                )
        return "\n".join(lines)

    def detect_skill_references(self, text: str) -> list[str]:
        """Detect skill names explicitly mentioned in free-form text."""
        lowered = text.lower()
        detected: list[str] = []
        for skill in self.list_skills(filter_unavailable=False):
            name = skill["name"]
            pattern = rf"(?<![A-Za-z0-9_])\$?{re.escape(name.lower())}(?![A-Za-z0-9_])"
            if re.search(pattern, lowered):
                detected.append(name)
        return detected

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """
        Load specific skills for inclusion in agent context.

        Args:
            skill_names: List of skill names to load.

        Returns:
            Formatted skills content.
        """
        parts = []
        for name in skill_names:
            content = self.load_skill(name)
            if content:
                content = self._strip_frontmatter(content)
                parts.append(f"### Skill: {name}\n\n{content}")

        return "\n\n---\n\n".join(parts) if parts else ""

    def build_skills_summary(self) -> str:
        """
        Build a summary of all skills (name, description, path, availability).

        This is used for progressive loading - the agent can read the full
        skill content using read_file when needed.

        Returns:
            XML-formatted skills summary.
        """
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""

        def escape_xml(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        lines = ["<skills>"]
        for s in all_skills:
            name = escape_xml(s["name"])
            path = s["path"]
            desc = escape_xml(self._get_skill_description(s["name"]))
            skill_meta = self._get_skill_meta(s["name"])
            available = self._check_requirements(skill_meta)

            lines.append(f"  <skill available=\"{str(available).lower()}\">")
            lines.append(f"    <name>{name}</name>")
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>{path}</location>")

            # Show missing requirements for unavailable skills
            if not available:
                missing = self._get_missing_requirements(skill_meta)
                if missing:
                    lines.append(f"    <requires>{escape_xml(missing)}</requires>")

            lines.append("  </skill>")
        lines.append("</skills>")

        return "\n".join(lines)

    def _resolve_skill_dir(self, name: str) -> Path | None:
        """Resolve a skill directory from workspace or built-in skills."""
        workspace_dir = self.workspace_skills / name
        if workspace_dir.is_dir():
            return workspace_dir

        if self.builtin_skills:
            builtin_dir = self.builtin_skills / name
            if builtin_dir.is_dir():
                return builtin_dir

        return None

    def _get_missing_requirements(self, skill_meta: dict) -> str:
        """Get a description of missing requirements."""
        missing = []
        requires = skill_meta.get("requires", {})
        for b in requires.get("bins", []):
            if not shutil.which(b):
                missing.append(f"CLI: {b}")
        for env in requires.get("env", []):
            if not os.environ.get(env):
                missing.append(f"ENV: {env}")
        return ", ".join(missing)

    @staticmethod
    def _classify_source_priority(label: str, url: str) -> str:
        """Infer whether a source is primary, fallback, or signal-only."""
        normalized = f"{label} {url}".lower()
        signal_markers = ("signal-only", "(signal", "signal)")
        if any(marker in normalized for marker in signal_markers):
            return "signal-only"
        fallback_markers = ("rsshub", "mirror", "fallback", "reader")
        if any(marker in normalized for marker in fallback_markers):
            return "fallback"
        return "primary"

    def _get_skill_description(self, name: str) -> str:
        """Get the description of a skill from its frontmatter."""
        meta = self.get_skill_metadata(name)
        if meta and meta.get("description"):
            return meta["description"]
        return name  # Fallback to skill name

    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter from markdown content."""
        if content.startswith("---"):
            match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
            if match:
                return content[match.end():].strip()
        return content

    def _parse_nanobot_metadata(self, raw: str) -> dict:
        """Parse skill metadata JSON from frontmatter (supports nanobot and openclaw keys)."""
        try:
            data = json.loads(raw)
            return data.get("nanobot", data.get("openclaw", {})) if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}

    def _check_requirements(self, skill_meta: dict) -> bool:
        """Check if skill requirements are met (bins, env vars)."""
        requires = skill_meta.get("requires", {})
        for b in requires.get("bins", []):
            if not shutil.which(b):
                return False
        for env in requires.get("env", []):
            if not os.environ.get(env):
                return False
        return True

    def _get_skill_meta(self, name: str) -> dict:
        """Get nanobot metadata for a skill (cached in frontmatter)."""
        meta = self.get_skill_metadata(name) or {}
        return self._parse_nanobot_metadata(meta.get("metadata", ""))

    def get_always_skills(self) -> list[str]:
        """Get skills marked as always=true that meet requirements."""
        result = []
        for s in self.list_skills(filter_unavailable=True):
            meta = self.get_skill_metadata(s["name"]) or {}
            skill_meta = self._parse_nanobot_metadata(meta.get("metadata", ""))
            if skill_meta.get("always") or meta.get("always"):
                result.append(s["name"])
        return result

    def get_skill_metadata(self, name: str) -> dict | None:
        """
        Get metadata from a skill's frontmatter.

        Args:
            name: Skill name.

        Returns:
            Metadata dict or None.
        """
        content = self.load_skill(name)
        if not content:
            return None

        if content.startswith("---"):
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if match:
                # Simple YAML parsing
                metadata = {}
                for line in match.group(1).split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        metadata[key.strip()] = value.strip().strip('"\'')
                return metadata

        return None

"""Coding model routing helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nanobot.providers.base import LLMProvider
from nanobot.providers.registry import find_by_name

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop


@dataclass(frozen=True)
class CodingRouteCandidate:
    source_model: str
    normalized_model: str
    provider: LLMProvider
    model: str
    provider_name: str | None
    normalization_note: str | None = None


class CodingRouteController:
    """Resolve and manage coding-specific model routing."""

    def __init__(self, loop: AgentLoop):
        self.loop = loop

    def raw_models(self) -> list[str]:
        primary = str(getattr(self.loop.coding_config, "primary_model", "")).strip()
        fallbacks = list(getattr(self.loop.coding_config, "fallback_models", []) or [])
        ordered = [primary, *(str(model).strip() for model in fallbacks)]
        return [model for model in ordered if model]

    @staticmethod
    def normalize_model_name(model_name: str) -> tuple[str | None, str | None]:
        model = model_name.strip()
        if not model:
            return None, "empty model name"

        if "/" in model:
            prefix = model.split("/", 1)[0].lower().replace("-", "_")
            if not find_by_name(prefix):
                return None, f"unknown provider prefix `{prefix}`"
            return model, None

        lowered = model.lower()
        if "codex" in lowered:
            return f"github-copilot/{model}", "normalized bare codex model to github-copilot prefix"
        if lowered.startswith("claude"):
            return f"anthropic/{model}", "normalized bare claude model to anthropic prefix"
        return model, None

    def cooldown_remaining(self, normalized_model: str) -> int:
        until = self.loop._coding_model_cooldowns.get(normalized_model, 0.0)
        if until <= 0.0:
            return 0
        remaining = int(until - time.monotonic())
        return remaining if remaining > 0 else 0

    def mark_failure(self, normalized_model: str) -> None:
        cooldown = max(0, int(getattr(self.loop.coding_config, "model_fail_cooldown_seconds", 0)))
        if cooldown <= 0:
            self.loop._coding_model_cooldowns.pop(normalized_model, None)
            return
        self.loop._coding_model_cooldowns[normalized_model] = time.monotonic() + cooldown

    def resolve_candidates(self) -> tuple[list[CodingRouteCandidate], list[str], list[str]]:
        candidates: list[CodingRouteCandidate] = []
        resolved_lines: list[str] = []
        skipped_lines: list[str] = []
        seen_models: set[str] = set()

        for source_model in self.raw_models():
            normalized_model, normalization_note = self.normalize_model_name(source_model)
            if not normalized_model:
                skipped_lines.append(f"- `{source_model}`: invalid ({normalization_note})")
                continue
            if normalized_model in seen_models:
                continue
            seen_models.add(normalized_model)

            if remaining := self.cooldown_remaining(normalized_model):
                skipped_lines.append(
                    f"- `{source_model}` -> `{normalized_model}`: cooling down ({remaining}s remaining)"
                )
                continue

            if self.loop._provider_switcher:
                try:
                    provider, model, provider_name = self.loop._provider_switcher(normalized_model)
                except Exception as exc:
                    skipped_lines.append(
                        f"- `{source_model}` -> `{normalized_model}`: unavailable ({exc})"
                    )
                    continue
            elif normalized_model == self.loop.model:
                provider = self.loop.provider
                model = self.loop.model
                provider_name = self.loop.provider_name
            else:
                skipped_lines.append(
                    f"- `{source_model}` -> `{normalized_model}`: unavailable (provider switcher not configured)"
                )
                continue

            candidate = CodingRouteCandidate(
                source_model=source_model,
                normalized_model=normalized_model,
                provider=provider,
                model=model,
                provider_name=provider_name,
                normalization_note=normalization_note,
            )
            candidates.append(candidate)
            note = f"; {normalization_note}" if normalization_note else ""
            resolved_lines.append(
                f"- `{source_model}` -> `{candidate.model}` (provider: `{candidate.provider_name or 'unknown'}`{note})"
            )

        self.loop._last_coding_route_resolved = list(resolved_lines)
        self.loop._last_coding_route_skipped = list(skipped_lines)
        return candidates, resolved_lines, skipped_lines

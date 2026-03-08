"""Curated model catalog for runtime model listing and selection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from nanobot.providers.factory import ProviderConfigError, resolve_switch_selection
from nanobot.providers.registry import PROVIDERS, find_by_name

if TYPE_CHECKING:
    from nanobot.config.schema import CodingConfig, Config


@dataclass(frozen=True)
class AvailableModel:
    """One selectable runtime model entry."""

    model: str
    provider_name: str | None = None
    source: str | None = None


_PROVIDER_MODEL_CATALOG: dict[str, tuple[str, ...]] = {
    "anthropic": (
        "anthropic/claude-opus-4-5",
        "anthropic/claude-sonnet-4-5",
        "anthropic/claude-3-7-sonnet",
    ),
    "openai": (
        "gpt-5.4",
        "gpt-5.1",
        "gpt-4.1",
        "gpt-4o",
    ),
    "openai_codex": (
        "openai-codex/gpt-5.1-codex",
    ),
    "github_copilot": (
        "github-copilot/gpt-5.3-codex",
        "github-copilot/gpt-5.1-codex",
    ),
    "deepseek": (
        "deepseek/deepseek-chat",
        "deepseek/deepseek-reasoner",
    ),
    "gemini": (
        "gemini/gemini-2.5-pro",
        "gemini/gemini-2.5-flash",
    ),
    "dashscope": (
        "dashscope/qwen-max",
        "dashscope/qwen-plus",
        "dashscope/qwen-turbo",
    ),
    "moonshot": (
        "moonshot/kimi-k2.5",
        "moonshot/moonshot-v1-128k",
    ),
    "minimax": (
        "minimax/MiniMax-M2.1",
    ),
    "zhipu": (
        "zai/glm-4.5",
        "zai/glm-4.5-air",
    ),
    "groq": (
        "groq/llama-3.3-70b-versatile",
        "groq/llama-3.1-8b-instant",
    ),
    # Gateways can route multiple upstreams, so expose a compact cross-provider set.
    "openrouter": (
        "anthropic/claude-opus-4-5",
        "anthropic/claude-sonnet-4-5",
        "gpt-5.4",
        "gpt-5.1",
        "gemini/gemini-2.5-pro",
        "deepseek/deepseek-chat",
    ),
    "aihubmix": (
        "anthropic/claude-opus-4-5",
        "gpt-5.4",
        "gemini/gemini-2.5-pro",
    ),
    "aicodewith": (
        "anthropic/claude-opus-4-5",
        "gpt-5.4",
        "deepseek/deepseek-chat",
    ),
    "siliconflow": (
        "Qwen/Qwen3-32B",
        "deepseek-ai/DeepSeek-V3",
    ),
    "volcengine": (
        "doubao-1-5-pro-32k-250115",
        "deepseek-v3-250324",
    ),
}


def build_available_models(
    config: "Config",
    *,
    default_model: str,
    default_provider_name: str | None,
    current_model: str | None = None,
    current_provider_name: str | None = None,
    coding_config: "CodingConfig | None" = None,
) -> list[AvailableModel]:
    """Build a curated list of selectable models for the current runtime."""

    options: list[AvailableModel] = []
    seen: set[str] = set()

    def add(model: str, provider_name: str | None = None, source: str | None = None) -> None:
        normalized = str(model or "").strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        options.append(
            AvailableModel(
                model=normalized,
                provider_name=provider_name or _infer_provider_name(
                    config,
                    normalized,
                    default_model=default_model,
                    default_provider_name=default_provider_name,
                    current_model=current_model,
                    current_provider_name=current_provider_name,
                ),
                source=source,
            )
        )

    add(default_model, default_provider_name, "default")
    if current_model:
        add(current_model, current_provider_name, "current")

    for model in _coding_models(coding_config):
        add(model, source="coding")

    for provider_name in _configured_provider_names(
        config,
        default_provider_name=default_provider_name,
        current_provider_name=current_provider_name,
    ):
        for model in _PROVIDER_MODEL_CATALOG.get(provider_name, ()):
            add(model, provider_name, "catalog")

    return options


def _coding_models(coding_config: "CodingConfig | None") -> list[str]:
    if coding_config is None:
        return []
    primary = str(getattr(coding_config, "primary_model", "")).strip()
    fallbacks = [str(model).strip() for model in getattr(coding_config, "fallback_models", []) or []]
    return [model for model in [primary, *fallbacks] if model]


def _configured_provider_names(
    config: "Config",
    *,
    default_provider_name: str | None,
    current_provider_name: str | None,
) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def add(name: str | None) -> None:
        if not name or name in seen:
            return
        seen.add(name)
        names.append(name)

    add(default_provider_name)
    add(current_provider_name)

    forced = str(config.agents.defaults.provider or "").strip()
    if forced and forced != "auto":
        add(forced)

    for spec in PROVIDERS:
        provider_cfg = getattr(config.providers, spec.name, None)
        if provider_cfg is None:
            continue
        if _provider_looks_available(spec.name, provider_cfg.api_key, provider_cfg.api_base):
            add(spec.name)

    return names


def _provider_looks_available(
    provider_name: str,
    api_key: str | None,
    api_base: str | None,
) -> bool:
    spec = find_by_name(provider_name)
    if spec is None:
        return False
    if spec.is_oauth:
        return True
    if provider_name == "azure_openai":
        return bool(api_key and api_base)
    if provider_name in {"custom", "vllm"}:
        return bool(api_base)
    return bool(api_key)


def _infer_provider_name(
    config: "Config",
    model: str,
    *,
    default_model: str,
    default_provider_name: str | None,
    current_model: str | None,
    current_provider_name: str | None,
) -> str | None:
    if current_model and model == current_model and current_provider_name:
        return current_provider_name
    if model == default_model and default_provider_name:
        return default_provider_name
    try:
        return resolve_switch_selection(
            config,
            model,
            default_model=default_model,
            default_provider_name=default_provider_name,
        ).provider_name
    except ProviderConfigError:
        return config.get_provider_name(model)

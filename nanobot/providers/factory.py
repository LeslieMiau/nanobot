"""Provider construction helpers shared by CLI and runtime model switching."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from nanobot.config.schema import Config
from nanobot.providers.azure_openai_provider import AzureOpenAIProvider
from nanobot.providers.base import LLMProvider
from nanobot.providers.openai_codex_provider import OpenAICodexProvider
from nanobot.providers.registry import PROVIDERS, find_by_name


class ProviderConfigError(ValueError):
    """Raised when a target model/provider cannot be activated with current config."""


@dataclass(frozen=True)
class ProviderSelection:
    """Resolved runtime selection for a requested model switch."""

    model: str
    provider_name: str


def create_provider(config: Config, model: str | None = None, provider_name: str | None = None) -> LLMProvider:
    """Build a provider instance for the target model/provider pair."""
    model = model or config.agents.defaults.model
    provider_name = provider_name or config.get_provider_name(model)
    p = getattr(config.providers, provider_name, None) if provider_name else None
    _ensure_provider_ready(provider_name)

    if provider_name == "openai_codex" or model.startswith("openai-codex/"):
        return OpenAICodexProvider(default_model=model)

    if provider_name == "custom":
        from nanobot.providers.custom_provider import CustomProvider

        return CustomProvider(
            api_key=p.api_key if p else "no-key",
            api_base=config.get_api_base(model) or "http://localhost:8000/v1",
            default_model=model,
        )

    if provider_name == "azure_openai":
        if not p or not p.api_key or not p.api_base:
            raise ProviderConfigError(
                "Azure OpenAI requires `providers.azure_openai.apiKey` and `apiBase`."
            )
        return AzureOpenAIProvider(
            api_key=p.api_key,
            api_base=p.api_base,
            default_model=model,
        )

    from nanobot.providers.litellm_provider import LiteLLMProvider

    spec = find_by_name(provider_name) if provider_name else None
    if provider_name and not model.startswith("bedrock/") and not (p and p.api_key) and not (spec and spec.is_oauth):
        raise ProviderConfigError(
            f"Provider `{provider_name}` is not configured for model `{model}`."
        )

    return LiteLLMProvider(
        api_key=p.api_key if p else None,
        api_base=config.get_api_base(model),
        default_model=model,
        extra_headers=p.extra_headers if p else None,
        provider_name=provider_name,
    )


def resolve_switch_selection(
    config: Config,
    requested_model: str | None,
    *,
    default_model: str,
    default_provider_name: str | None,
) -> ProviderSelection:
    """Resolve the runtime provider to use when switching models."""
    if not requested_model:
        return ProviderSelection(
            model=default_model,
            provider_name=default_provider_name or config.get_provider_name(default_model) or "custom",
        )

    model = requested_model.strip()
    explicit_provider = _explicit_provider_name(model)
    if explicit_provider:
        return ProviderSelection(model=model, provider_name=explicit_provider)

    lowered = model.lower()
    if "codex" in lowered and default_provider_name in {"github_copilot", "openai_codex"}:
        return ProviderSelection(model=model, provider_name=default_provider_name)

    matched = _match_provider_by_model_name(model)
    if matched:
        return ProviderSelection(model=model, provider_name=matched)

    forced = config.agents.defaults.provider
    if forced != "auto":
        return ProviderSelection(model=model, provider_name=forced)

    raise ProviderConfigError(
        f"Cannot infer provider for model `{model}`. Use an explicit prefix like "
        "`github-copilot/{model}` or `openai-codex/{model}`."
    )


def build_runtime_provider(
    config: Config,
    requested_model: str | None,
    *,
    default_model: str,
    default_provider_name: str | None,
) -> tuple[LLMProvider, ProviderSelection]:
    """Resolve a runtime model switch and create the matching provider instance."""
    selection = resolve_switch_selection(
        config,
        requested_model,
        default_model=default_model,
        default_provider_name=default_provider_name,
    )
    provider = create_provider(config, model=selection.model, provider_name=selection.provider_name)
    return provider, selection


def _explicit_provider_name(model: str) -> str | None:
    if "/" not in model:
        return None
    prefix = model.split("/", 1)[0].lower().replace("-", "_")
    return prefix if find_by_name(prefix) else None


def _match_provider_by_model_name(model: str) -> str | None:
    lowered = model.lower()
    normalized = lowered.replace("-", "_")

    def _kw_matches(kw: str) -> bool:
        return kw in lowered or kw.replace("-", "_") in normalized

    if "codex" in lowered:
        # Bare codex models are ambiguous. Prefer explicit provider prefixes.
        return None

    for spec in PROVIDERS:
        if any(_kw_matches(kw) for kw in spec.keywords):
            return spec.name
    return None


def _ensure_provider_ready(provider_name: str | None) -> None:
    """Raise when a provider is configured but not currently usable."""
    if provider_name != "github_copilot":
        return
    if _github_copilot_is_authenticated():
        return
    raise ProviderConfigError(
        "Provider `github_copilot` is not authenticated. "
        "Run `nanobot login github_copilot` first."
    )


def _github_copilot_is_authenticated() -> bool:
    """Return True when GitHub Copilot can refresh or reuse a local token."""
    token_dir = Path(
        os.getenv(
            "GITHUB_COPILOT_TOKEN_DIR",
            str(Path.home() / ".config" / "litellm" / "github_copilot"),
        )
    )
    access_token_file = token_dir / os.getenv("GITHUB_COPILOT_ACCESS_TOKEN_FILE", "access-token")
    api_key_file = token_dir / os.getenv("GITHUB_COPILOT_API_KEY_FILE", "api-key.json")

    if access_token_file.is_file():
        try:
            if access_token_file.read_text().strip():
                return True
        except OSError:
            pass

    if not api_key_file.is_file():
        return False
    try:
        api_key_info = json.loads(api_key_file.read_text())
    except (OSError, json.JSONDecodeError):
        return False

    token = str(api_key_info.get("token") or "").strip()
    expires_at = api_key_info.get("expires_at")
    if not token:
        return False
    try:
        return float(expires_at or 0) > datetime.now().timestamp()
    except (TypeError, ValueError):
        return False

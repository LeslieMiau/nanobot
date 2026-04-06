import pytest

from nanobot.config.schema import Config
from nanobot.providers.catalog import build_available_models
from nanobot.providers.custom_provider import CustomProvider
from nanobot.providers.factory import ProviderConfigError, create_provider, resolve_switch_selection
from nanobot.providers.openai_codex_provider import OpenAICodexProvider


def test_resolve_switch_selection_prefers_explicit_provider_prefix() -> None:
    config = Config()
    selection = resolve_switch_selection(
        config,
        "github-copilot/gpt-5.3-codex",
        default_model=config.agents.defaults.model,
        default_provider_name="custom",
    )

    assert selection.model == "github-copilot/gpt-5.3-codex"
    assert selection.provider_name == "github_copilot"


def test_resolve_switch_selection_reuses_default_codex_provider() -> None:
    config = Config()
    selection = resolve_switch_selection(
        config,
        "gpt-5.3-codex",
        default_model="github-copilot/gpt-5.3-codex",
        default_provider_name="github_copilot",
    )

    assert selection.provider_name == "github_copilot"


def test_resolve_switch_selection_rejects_ambiguous_bare_codex_model() -> None:
    config = Config()

    try:
        resolve_switch_selection(
            config,
            "gpt-5.3-codex",
            default_model=config.agents.defaults.model,
            default_provider_name="custom",
        )
    except ProviderConfigError as e:
        assert "Cannot infer provider" in str(e)
    else:
        raise AssertionError("Expected ProviderConfigError for bare codex model")


def test_create_provider_rejects_unauthenticated_github_copilot(monkeypatch: pytest.MonkeyPatch) -> None:
    config = Config()
    monkeypatch.setattr(
        "nanobot.providers.factory._github_copilot_is_authenticated",
        lambda: False,
    )

    with pytest.raises(ProviderConfigError, match="nanobot login github_copilot"):
        create_provider(
            config,
            model="github-copilot/gpt-5.3-codex",
            provider_name="github_copilot",
        )


def test_create_provider_uses_openai_codex_for_default_config() -> None:
    config = Config()

    provider = create_provider(config)

    assert isinstance(provider, OpenAICodexProvider)
    assert provider.get_default_model() == "gpt-5.1"
    assert provider.response_verbosity == "low"


def test_create_provider_uses_custom_provider_for_aicodewith() -> None:
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "provider": "aicodewith",
                    "model": "gpt-5.4",
                }
            },
            "providers": {
                "aicodewith": {
                    "apiKey": "sk-acw-test",
                }
            },
        }
    )

    provider = create_provider(
        config,
        model="gpt-5.4",
        provider_name="aicodewith",
    )

    assert isinstance(provider, CustomProvider)
    assert provider.get_default_model() == "gpt-5.4"


def test_build_available_models_uses_openai_codex_for_default_entry() -> None:
    config = Config()

    models = build_available_models(
        config,
        default_model=config.agents.defaults.model,
        default_provider_name=config.get_provider_name(config.agents.defaults.model),
        coding_config=config.agents.defaults.coding,
    )

    assert any(
        model.model == "gpt-5.1" and model.provider_name == "openai_codex"
        for model in models
    )
    assert not any(model.model == "openai-codex/gpt-5.1-codex" for model in models)


def test_resolve_switch_selection_reuses_default_openai_codex_for_bare_gpt_model() -> None:
    config = Config()

    selection = resolve_switch_selection(
        config,
        "gpt-5.1",
        default_model="gpt-5.1",
        default_provider_name="openai_codex",
    )

    assert selection.provider_name == "openai_codex"

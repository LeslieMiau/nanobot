from nanobot.config.schema import Config
from nanobot.providers.factory import ProviderConfigError, resolve_switch_selection


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

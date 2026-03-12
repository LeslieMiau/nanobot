from nanobot.config.schema import Config


def test_persona_defaults_are_backward_compatible() -> None:
    config = Config()
    persona = config.agents.defaults.persona
    coding = config.agents.defaults.coding

    assert config.agents.defaults.model == "gpt-5.1"
    assert config.agents.defaults.general_model == "gpt-5.1"
    assert config.agents.defaults.automation_model == "gpt-5.1"
    assert config.agents.defaults.provider == "auto"
    assert config.get_provider_name() == "openai_codex"
    assert persona.mode == "default"
    assert persona.dialect == "tw_s1"
    assert persona.script == "simplified"
    assert persona.intensity == "adaptive"
    assert persona.quote_retrieval is True
    assert persona.apply_to == "chat_only"
    assert config.channels.send_progress is False
    assert config.channels.send_tool_hints is False
    assert coding.enabled is True
    assert coding.auto_detect is True
    assert coding.disable_persona is True
    assert coding.require_plan_for_large_changes is True
    assert coding.enforce_read_before_write is True
    assert coding.require_verification_after_edits is True
    assert coding.primary_model == "gpt-5.4"
    assert coding.fallback_models == [
        "github-copilot/gpt-5.3-codex",
        "anthropic/claude-opus-4-5",
        "anthropic/claude-sonnet-4-5",
    ]
    assert coding.model_fail_cooldown_seconds == 600


def test_persona_legacy_language_maps_to_script() -> None:
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "persona": {
                        "mode": "shinchan_tw_s1",
                        "language": "zh-tw",
                    }
                }
            }
        }
    )
    assert config.agents.defaults.persona.script == "traditional"


def test_persona_modern_script_takes_precedence_over_legacy_language() -> None:
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "persona": {
                        "mode": "shinchan_tw_s1",
                        "language": "zh-tw",
                        "script": "simplified",
                    }
                }
            }
        }
    )
    assert config.agents.defaults.persona.script == "simplified"


def test_coding_defaults_are_backward_compatible_when_missing_from_input() -> None:
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "model": "gpt-5.4",
                }
            }
        }
    )

    assert config.agents.defaults.general_model == "gpt-5.4"
    assert config.agents.defaults.automation_model == "gpt-5.4"
    coding = config.agents.defaults.coding
    assert coding.enabled is True
    assert coding.auto_detect is True
    assert coding.disable_persona is True
    assert coding.require_plan_for_large_changes is True
    assert coding.enforce_read_before_write is True
    assert coding.require_verification_after_edits is True
    assert coding.primary_model == "gpt-5.4"
    assert coding.fallback_models == [
        "github-copilot/gpt-5.3-codex",
        "anthropic/claude-opus-4-5",
        "anthropic/claude-sonnet-4-5",
    ]
    assert coding.model_fail_cooldown_seconds == 600

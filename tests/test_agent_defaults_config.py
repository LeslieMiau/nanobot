from nanobot.config.schema import Config


def test_agent_defaults_are_backward_compatible() -> None:
    config = Config()
    coding = config.agents.defaults.coding
    dumped = config.agents.defaults.model_dump()

    assert config.agents.defaults.model == "gpt-5.1"
    assert config.agents.defaults.general_model == "gpt-5.1"
    assert config.agents.defaults.automation_model == "gpt-5.1"
    assert config.agents.defaults.provider == "auto"
    assert config.get_provider_name() == "openai_codex"
    assert "persona" not in dumped
    assert config.channels.send_progress is False
    assert config.channels.send_tool_hints is False
    assert coding.enabled is True
    assert coding.auto_detect is True
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
    assert "disable_persona" not in coding.model_dump()


def test_legacy_persona_config_is_ignored() -> None:
    config = Config.model_validate(
        {
            "agents": {
                "defaults": {
                    "persona": {
                        "mode": "shinchan_tw_s1",
                        "language": "zh-tw",
                    },
                    "coding": {
                        "disable_persona": False,
                    },
                }
            }
        }
    )

    dumped = config.agents.defaults.model_dump()
    assert "persona" not in dumped
    assert "disable_persona" not in dumped["coding"]


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
    assert "disable_persona" not in coding.model_dump()

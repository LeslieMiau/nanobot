from nanobot.config.schema import Config


def test_persona_defaults_are_backward_compatible() -> None:
    config = Config()
    persona = config.agents.defaults.persona

    assert persona.mode == "default"
    assert persona.dialect == "tw_s1"
    assert persona.script == "simplified"
    assert persona.intensity == "adaptive"
    assert persona.quote_retrieval is True


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

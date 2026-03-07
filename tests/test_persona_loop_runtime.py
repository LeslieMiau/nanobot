from __future__ import annotations

from nanobot.agent.loop import AgentLoop
from nanobot.config.schema import PersonaConfig
from nanobot.persona.engine import PersonaEngine
from nanobot.providers.base import LLMProvider, LLMResponse


class _Provider(LLMProvider):
    def __init__(self):
        super().__init__(api_key=None, api_base=None)
        self.temperatures: list[float] = []

    async def chat(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
    ) -> LLMResponse:
        self.temperatures.append(float(temperature))
        return LLMResponse(content="ok")

    def get_default_model(self) -> str:
        return "dummy"


class _Tools:
    @staticmethod
    def get_definitions() -> list:
        return []


class _Context:
    @staticmethod
    def add_assistant_message(
        messages,
        content,
        tool_calls=None,
        reasoning_content=None,
        thinking_blocks=None,
    ):
        messages.append({"role": "assistant", "content": content})
        return messages


async def test_run_agent_loop_uses_temperature_override() -> None:
    provider = _Provider()
    loop = AgentLoop.__new__(AgentLoop)
    loop.provider = provider
    loop.tools = _Tools()
    loop.context = _Context()
    loop.max_iterations = 1
    loop.model = "dummy"
    loop.temperature = 0.1
    loop.max_tokens = 256
    loop.reasoning_effort = None

    final, _, _, _ = await loop._run_agent_loop(
        initial_messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        temperature_override=0.66,
    )

    assert final == "ok"
    assert provider.temperatures == [0.66]


async def test_apply_persona_output_controls_updates_final_assistant_message() -> None:
    provider = _Provider()
    loop = AgentLoop.__new__(AgentLoop)
    loop.coding_config = None
    loop.persona = PersonaEngine(
        PersonaConfig(mode="shinchan_tw_s1", dialect="tw_s1", script="simplified", intensity="adaptive")
    )
    loop.provider = provider
    loop.model = "dummy"
    loop.max_tokens = 512
    loop.reasoning_effort = None

    all_messages = [{"role": "assistant", "content": "這樣喔，你賴東東不錯喔"}]
    class _CodingConfig:
        disable_persona = False

    loop.coding_config = _CodingConfig()
    normalized = await loop._apply_persona_output_controls(all_messages[0]["content"], all_messages)

    assert normalized == "这样喔，你赖东东不错喔"
    assert all_messages[0]["content"] == "这样喔，你赖东东不错喔"


async def test_apply_persona_output_controls_skips_when_coding_mode_disables_persona() -> None:
    provider = _Provider()
    loop = AgentLoop.__new__(AgentLoop)
    loop.persona = PersonaEngine(
        PersonaConfig(mode="shinchan_tw_s1", dialect="tw_s1", script="simplified", intensity="adaptive")
    )
    loop.provider = provider
    loop.model = "dummy"
    loop.max_tokens = 512
    loop.reasoning_effort = None

    class _CodingConfig:
        disable_persona = True

    loop.coding_config = _CodingConfig()
    all_messages = [{"role": "assistant", "content": "這樣喔，你賴東東不錯喔"}]
    normalized = await loop._apply_persona_output_controls(
        all_messages[0]["content"],
        all_messages,
        coding_enabled=True,
    )

    assert normalized == "這樣喔，你賴東東不錯喔"
    assert all_messages[0]["content"] == "這樣喔，你賴東東不錯喔"
    assert provider.temperatures == []

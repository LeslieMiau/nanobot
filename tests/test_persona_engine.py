from __future__ import annotations

from nanobot.config.schema import PersonaConfig
from nanobot.persona.engine import PersonaEngine
from nanobot.providers.base import LLMProvider, LLMResponse


class _DummyProvider(LLMProvider):
    def __init__(self):
        super().__init__(api_key=None, api_base=None)
        self.calls = 0

    async def chat(
        self,
        messages,
        tools=None,
        model=None,
        max_tokens=4096,
        temperature=0.7,
        reasoning_effort=None,
    ) -> LLMResponse:
        self.calls += 1
        return LLMResponse(content="重写后的文本")

    def get_default_model(self) -> str:
        return "test-model"


def test_persona_runtime_hints_include_quote_retrieval() -> None:
    engine = PersonaEngine(
        PersonaConfig(
            mode="shinchan_tw_s1",
            dialect="tw_s1",
            script="simplified",
            intensity="adaptive",
            quote_retrieval=True,
        )
    )
    hints = engine.build_runtime_hints("你赖东东不错哦")

    assert hints is not None
    assert "台版《蜡笔小新》S1语感" in hints
    assert "简体中文" in hints
    assert "检索增强" in hints


def test_persona_adaptive_temperature_by_scene() -> None:
    engine = PersonaEngine(
        PersonaConfig(mode="shinchan_tw_s1", dialect="tw_s1", script="simplified", intensity="adaptive")
    )

    assert engine.recommended_temperature("今天要不要吃饼干", 0.1) == 0.85
    assert engine.recommended_temperature("请帮我修复这个报错", 0.1) == 0.55
    assert engine.recommended_temperature("这个医疗建议是否有风险", 0.1) == 0.25


def test_persona_chat_only_applies_only_to_chat_scene() -> None:
    engine = PersonaEngine(
        PersonaConfig(mode="shinchan_tw_s1", dialect="tw_s1", script="simplified", intensity="adaptive")
    )

    assert engine.should_apply("今天要不要吃饼干") is True
    assert engine.should_apply("请帮我修复这个报错") is False
    assert engine.should_apply("帮我执行定时任务", system_turn=True) is False


async def test_normalize_output_converts_to_simplified_locally() -> None:
    engine = PersonaEngine(
        PersonaConfig(mode="shinchan_tw_s1", dialect="tw_s1", script="simplified", intensity="adaptive")
    )
    provider = _DummyProvider()

    text = "這樣喔，你賴東東不錯喔"
    normalized = await engine.normalize_output(
        text=text,
        provider=provider,
        model="test-model",
        max_tokens=512,
    )

    assert normalized == "这样喔，你赖东东不错喔"
    assert provider.calls == 0


async def test_default_mode_keeps_original_behavior() -> None:
    engine = PersonaEngine(PersonaConfig(mode="default"))
    provider = _DummyProvider()
    original = "這樣喔，你賴東東不錯喔"

    normalized = await engine.normalize_output(
        text=original,
        provider=provider,
        model="test-model",
        max_tokens=512,
    )

    assert normalized == original
    assert engine.build_runtime_hints("你赖东东不错哦") is None
    assert engine.recommended_temperature("hello", 0.33) == 0.33
    assert provider.calls == 0

from __future__ import annotations

from nanobot.providers.custom_provider import CustomProvider


def test_parse_plain_string_response() -> None:
    provider = CustomProvider(api_key="test", api_base="http://localhost:8000/v1", default_model="dummy")

    out = provider._parse("hello")

    assert out.content == "hello"
    assert out.finish_reason == "stop"


def test_parse_responses_payload_with_text_and_tool_call() -> None:
    provider = CustomProvider(api_key="test", api_base="https://api.with7.cn/chatgpt/v1", default_model="dummy")
    payload = {
        "status": "completed",
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "hello world"}],
            },
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "read_file",
                "arguments": "{\"path\":\"README.md\"}",
            },
        ],
    }

    out = provider._parse_responses(payload)

    assert out.content == "hello world"
    assert out.finish_reason == "stop"
    assert out.usage["prompt_tokens"] == 10
    assert out.usage["completion_tokens"] == 5
    assert out.tool_calls[0].name == "read_file"
    assert out.tool_calls[0].arguments["path"] == "README.md"

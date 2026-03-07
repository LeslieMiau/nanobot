"""Direct OpenAI-compatible provider — bypasses LiteLLM."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import json_repair
from openai import AsyncOpenAI

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.openai_codex_provider import _convert_messages, _convert_tools

_AICODEWITH_RESPONSES_BASE_KEYWORDS = (
    "api.aicodewith.com/chatgpt/v1",
    "api.with7.cn/chatgpt/v1",
)
_AICODEWITH_MODEL_FALLBACKS = (
    "gpt-5.2",
    "gpt-5.4",
    "gpt-5.3-codex",
)


class CustomProvider(LLMProvider):

    def __init__(self, api_key: str = "no-key", api_base: str = "http://localhost:8000/v1", default_model: str = "default"):
        super().__init__(api_key, api_base)
        self.default_model = default_model
        # Keep affinity stable for this provider instance to improve backend cache locality.
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=api_base,
            default_headers={"x-session-affinity": uuid.uuid4().hex},
        )

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
                   model: str | None = None, max_tokens: int = 4096, temperature: float = 0.7,
                   reasoning_effort: str | None = None) -> LLMResponse:
        requested_model = model or self.default_model
        if self._use_responses_api():
            last_error: Exception | None = None
            for candidate_model in self._candidate_models(requested_model):
                try:
                    return await self._chat_via_responses(
                        messages=messages,
                        tools=tools,
                        model=candidate_model,
                        max_tokens=max_tokens,
                        reasoning_effort=reasoning_effort,
                    )
                except RuntimeError as e:
                    msg = str(e)
                    if "该模型暂不支持" in msg or "model" in msg.lower() and "support" in msg.lower():
                        last_error = e
                        continue
                    return LLMResponse(content=f"Error: {e}", finish_reason="error")
                except Exception as e:
                    return LLMResponse(content=f"Error: {e}", finish_reason="error")
            return LLMResponse(content=f"Error: {last_error or 'No available model/channel'}", finish_reason="error")

        kwargs: dict[str, Any] = {
            "model": requested_model,
            "messages": self._sanitize_empty_content(messages),
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
        }
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        if tools:
            kwargs.update(tools=tools, tool_choice="auto")
        try:
            return self._parse(await self._client.chat.completions.create(**kwargs))
        except Exception as e:
            return LLMResponse(content=f"Error: {e}", finish_reason="error")

    def _use_responses_api(self) -> bool:
        """Route specific gateways via Responses API for compatibility."""
        base = (self.api_base or "").rstrip("/").lower()
        return any(k in base for k in _AICODEWITH_RESPONSES_BASE_KEYWORDS)

    @staticmethod
    def _candidate_models(requested_model: str) -> list[str]:
        """Try requested model first, then fall back to known working models."""
        candidates = [requested_model]
        candidates.extend(m for m in _AICODEWITH_MODEL_FALLBACKS if m != requested_model)
        return candidates

    async def _chat_via_responses(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        max_tokens: int,
        reasoning_effort: str | None,
    ) -> LLMResponse:
        if not self.api_base:
            raise RuntimeError("Responses API requires api_base.")

        system_prompt, input_items = _convert_messages(self._sanitize_empty_content(messages))
        body: dict[str, Any] = {
            "model": model,
            "store": False,
            "input": input_items,
            "max_output_tokens": max(1, max_tokens),
        }
        if system_prompt:
            body["instructions"] = system_prompt
        if reasoning_effort:
            body["reasoning"] = {"effort": reasoning_effort}
        if tools:
            body["tools"] = _convert_tools(tools)
            body["tool_choice"] = "auto"
            body["parallel_tool_calls"] = True

        url = f"{self.api_base.rstrip('/')}/responses"
        headers = {
            "Authorization": f"Bearer {self.api_key or ''}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, headers=headers, json=body)
        if response.status_code != 200:
            detail = response.text
            try:
                payload = response.json()
                detail = payload.get("error") or payload
            except Exception:
                pass
            raise RuntimeError(f"HTTP {response.status_code}: {detail}")

        payload = response.json()
        return self._parse_responses(payload)

    def _parse_responses(self, payload: dict[str, Any]) -> LLMResponse:
        """Parse OpenAI Responses API payload into standard LLMResponse."""
        text_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []

        output = payload.get("output") or []
        for item in output:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "message":
                for part in item.get("content") or []:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") in {"output_text", "text"}:
                        txt = part.get("text")
                        if isinstance(txt, str) and txt:
                            text_parts.append(txt)
            elif item_type == "function_call":
                args_raw = item.get("arguments") or "{}"
                args = args_raw
                if isinstance(args_raw, str):
                    try:
                        args = json_repair.loads(args_raw)
                    except Exception:
                        args = {"raw": args_raw}
                if not isinstance(args, dict):
                    args = {"raw": json.dumps(args, ensure_ascii=False)}
                tool_calls.append(
                    ToolCallRequest(
                        id=item.get("call_id") or item.get("id") or "fc_0",
                        name=item.get("name") or "",
                        arguments=args,
                    )
                )

        usage_raw = payload.get("usage") or {}
        usage = {
            "prompt_tokens": usage_raw.get("input_tokens", usage_raw.get("prompt_tokens", 0)),
            "completion_tokens": usage_raw.get("output_tokens", usage_raw.get("completion_tokens", 0)),
            "total_tokens": usage_raw.get("total_tokens", 0),
        }
        content = payload.get("output_text")
        if not isinstance(content, str) or not content:
            content = "".join(text_parts) or None

        status = payload.get("status") or "completed"
        finish_reason = "stop" if status == "completed" else ("error" if status in {"failed", "cancelled"} else "length")

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )

    def _parse(self, response: Any) -> LLMResponse:
        # Some OpenAI-compatible gateways may return plain text bodies for
        # non-tool calls. Accept this shape instead of crashing on .choices.
        if isinstance(response, str):
            return LLMResponse(content=response, finish_reason="stop")

        # Best-effort support for dict-like payloads from non-standard SDKs.
        if isinstance(response, dict):
            choices = response.get("choices") or []
            if choices:
                msg = choices[0].get("message") or {}
                return LLMResponse(
                    content=msg.get("content"),
                    finish_reason=choices[0].get("finish_reason") or "stop",
                    usage=response.get("usage") or {},
                )
            if isinstance(response.get("content"), str):
                return LLMResponse(content=response.get("content"), finish_reason="stop")

        choice = response.choices[0]
        msg = choice.message
        tool_calls = [
            ToolCallRequest(id=tc.id, name=tc.function.name,
                            arguments=json_repair.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments)
            for tc in (msg.tool_calls or [])
        ]
        u = response.usage
        return LLMResponse(
            content=msg.content, tool_calls=tool_calls, finish_reason=choice.finish_reason or "stop",
            usage={"prompt_tokens": u.prompt_tokens, "completion_tokens": u.completion_tokens, "total_tokens": u.total_tokens} if u else {},
            reasoning_content=getattr(msg, "reasoning_content", None) or None,
        )

    def get_default_model(self) -> str:
        return self.default_model

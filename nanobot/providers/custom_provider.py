"""Direct OpenAI-compatible provider — bypasses LiteLLM."""

from __future__ import annotations

import gzip
import json
import uuid
import zlib
from typing import Any
from urllib.parse import urlsplit

import httpx
import json_repair
from openai import AsyncOpenAI

from nanobot.providers.base import LLMProvider, LLMResponse, ToolCallRequest
from nanobot.providers.openai_responses import convert_messages, convert_tools

_AICODEWITH_HOST_KEYWORDS = ("aicodewith.com", "with7.cn")
_AICODEWITH_DEFAULT_ORIGIN = "https://api.aicodewith.com"
_AICODEWITH_OPENAI_PATH = "/chatgpt/v1"
_AICODEWITH_GEMINI_PATH = "/gemini_cli"


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
                   reasoning_effort: str | None = None,
                   tool_choice: str | dict[str, Any] | None = None) -> LLMResponse:
        requested_model = model or self.default_model

        if self._is_aicodewith_gateway():
            route = self._route_kind_for_model(requested_model)
            normalized_model = self._normalize_model_for_route(requested_model, route)

            if route == "anthropic":
                try:
                    return await self._chat_via_anthropic(
                        messages=messages,
                        tools=tools,
                        model=normalized_model,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )
                except Exception as e:
                    return LLMResponse(content=f"Error: {e}", finish_reason="error")

            if route == "gemini":
                try:
                    return await self._chat_via_gemini(
                        messages=messages,
                        tools=tools,
                        model=normalized_model,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )
                except Exception as e:
                    return LLMResponse(content=f"Error: {e}", finish_reason="error")

            return await self._chat_via_openai_responses_with_fallback(
                messages=messages,
                tools=tools,
                requested_model=normalized_model,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )

        if self._use_responses_api():
            normalized_model = self._normalize_model_for_route(requested_model, "openai")
            return await self._chat_via_openai_responses_with_fallback(
                messages=messages,
                tools=tools,
                requested_model=normalized_model,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )
        kwargs: dict[str, Any] = {
            "model": requested_model,
            "messages": self._sanitize_empty_content(messages),
            "max_tokens": max(1, max_tokens),
            "temperature": temperature,
        }
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        if tools:
            kwargs.update(tools=tools, tool_choice=tool_choice or "auto")
        try:
            return self._parse(await self._client.chat.completions.create(**kwargs))
        except Exception as e:
            return LLMResponse(content=f"Error: {e}", finish_reason="error")

    async def _chat_via_openai_responses_with_fallback(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        requested_model: str,
        max_tokens: int,
        reasoning_effort: str | None,
    ) -> LLMResponse:
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

    def _is_aicodewith_gateway(self) -> bool:
        base = (self.api_base or "").lower()
        return any(k in base for k in _AICODEWITH_HOST_KEYWORDS)

    def _use_responses_api(self) -> bool:
        """Route specific gateways via Responses API for compatibility."""
        base = (self.api_base or "").rstrip("/").lower()
        return "/chatgpt/v1" in base

    @staticmethod
    def _route_kind_for_model(model: str) -> str:
        lowered = (model or "").lower()
        if lowered.startswith("anthropic/") or "claude" in lowered:
            return "anthropic"
        if lowered.startswith("gemini/") or lowered.startswith("google/") or "gemini" in lowered:
            return "gemini"
        return "openai"

    @staticmethod
    def _normalize_model_for_route(model: str, route: str) -> str:
        normalized = model
        while "/" in normalized:
            prefix, rest = normalized.split("/", 1)
            normalized_prefix = prefix.lower().replace("-", "_")
            if normalized_prefix == "aicodewith":
                normalized = rest
                continue
            if route == "anthropic" and normalized_prefix in {"anthropic", "claude"}:
                normalized = rest
                continue
            if route == "gemini" and normalized_prefix in {"gemini", "google"}:
                normalized = rest
                continue
            if route == "openai" and normalized_prefix in {"openai", "chatgpt"}:
                normalized = rest
                continue
            break
        return normalized

    def _base_origin(self) -> str:
        base = (self.api_base or "").rstrip("/")
        if not base:
            return _AICODEWITH_DEFAULT_ORIGIN
        parsed = urlsplit(base)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        return _AICODEWITH_DEFAULT_ORIGIN

    def _openai_responses_base(self) -> str:
        base = (self.api_base or "").rstrip("/")
        if not base:
            return f"{_AICODEWITH_DEFAULT_ORIGIN}{_AICODEWITH_OPENAI_PATH}"
        lowered = base.lower()
        if "/chatgpt/v1" in lowered:
            return base
        return f"{self._base_origin()}{_AICODEWITH_OPENAI_PATH}"

    def _anthropic_base(self) -> str:
        return self._base_origin()

    def _gemini_base(self) -> str:
        base = (self.api_base or "").rstrip("/")
        if not base:
            return f"{_AICODEWITH_DEFAULT_ORIGIN}{_AICODEWITH_GEMINI_PATH}"
        parsed = urlsplit(base)
        origin = self._base_origin()
        path = (parsed.path or "").rstrip("/")
        if "/gemini_cli" in path.lower():
            idx = path.lower().index("/gemini_cli")
            return f"{origin}{path[: idx + len('/gemini_cli')]}"
        return f"{origin}{_AICODEWITH_GEMINI_PATH}"

    @staticmethod
    def _candidate_models(requested_model: str) -> list[str]:
        """AICodeWith should respect the requested model exactly."""
        return [requested_model]

    @staticmethod
    def _try_parse_json(text: str) -> Any | None:
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            try:
                return json_repair.loads(text)
            except Exception:
                return None

    @classmethod
    def _decode_json_body(cls, raw: bytes, content_encoding: str | None) -> tuple[Any | None, str]:
        """Best-effort decode JSON body, tolerating bad/incorrect encoding headers."""
        if not raw:
            return None, ""

        enc = (content_encoding or "").lower()
        candidates: list[bytes] = [raw]

        def _append(candidate: bytes) -> None:
            if candidate not in candidates:
                candidates.append(candidate)

        def _try_decompress(func) -> None:
            try:
                _append(func(raw))
            except Exception:
                pass

        if "gzip" in enc:
            _try_decompress(gzip.decompress)
            _try_decompress(lambda b: zlib.decompress(b, zlib.MAX_WBITS | 16))
        if "deflate" in enc:
            _try_decompress(zlib.decompress)
            _try_decompress(lambda b: zlib.decompress(b, -zlib.MAX_WBITS))
        if "gzip" not in enc and "deflate" not in enc:
            _try_decompress(gzip.decompress)
            _try_decompress(zlib.decompress)
            _try_decompress(lambda b: zlib.decompress(b, -zlib.MAX_WBITS))

        fallback_text = ""
        for payload in candidates:
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                text = payload.decode("utf-8", errors="replace")
            parsed = cls._try_parse_json(text)
            if parsed is not None:
                return parsed, text
            if not fallback_text:
                fallback_text = text
        return None, fallback_text

    async def _post_json_with_raw(
        self,
        *,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        params: dict[str, Any] | None = None,
    ) -> tuple[int, Any | None, str]:
        req_headers = dict(headers)
        req_headers.setdefault("Accept-Encoding", "identity")

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                url,
                headers=req_headers,
                params=params,
                json=body,
            ) as response:
                chunks: list[bytes] = []
                async for chunk in response.aiter_raw():
                    chunks.append(chunk)
                raw = b"".join(chunks)
                payload, text = self._decode_json_body(raw, response.headers.get("content-encoding"))
                if not text:
                    text = raw.decode("utf-8", errors="replace")
                return response.status_code, payload, text

    @staticmethod
    def _to_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") in {"text", "input_text", "output_text"} and isinstance(item.get("text"), str):
                        parts.append(item["text"])
                    elif item.get("type") == "image_url":
                        url = (item.get("image_url") or {}).get("url")
                        if isinstance(url, str) and url:
                            parts.append(f"[image:{url}]")
                elif isinstance(item, str):
                    parts.append(item)
            return "\n".join(p for p in parts if p)
        if isinstance(content, dict):
            return json.dumps(content, ensure_ascii=False)
        if content is None:
            return ""
        return str(content)

    @staticmethod
    def _parse_json_args(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                return json_repair.loads(value)
            except Exception:
                return {"raw": value}
        return {"raw": json.dumps(value, ensure_ascii=False)}

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

        system_prompt, input_items = convert_messages(self._sanitize_empty_content(messages))
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
            body["tools"] = convert_tools(tools)
            body["tool_choice"] = "auto"
            body["parallel_tool_calls"] = True

        base_url = self._openai_responses_base() if self._is_aicodewith_gateway() else self.api_base.rstrip("/")
        url = f"{base_url}/responses"
        headers = {
            "Authorization": f"Bearer {self.api_key or ''}",
            "Content-Type": "application/json",
        }
        status_code, payload, raw_text = await self._post_json_with_raw(
            url=url,
            headers=headers,
            body=body,
        )
        if status_code != 200:
            raise RuntimeError(self._format_http_error(status_code, payload, raw_text))
        if not isinstance(payload, dict):
            raise RuntimeError(f"HTTP {status_code}: Invalid JSON response: {raw_text[:300]}")
        return self._parse_responses(payload)

    async def _chat_via_anthropic(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        system_prompt, anthropic_messages = self._convert_messages_for_anthropic(self._sanitize_empty_content(messages))
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": max(1, max_tokens),
            "messages": anthropic_messages,
            "temperature": temperature,
        }
        if system_prompt:
            body["system"] = system_prompt

        if tools:
            converted_tools = self._convert_tools_for_anthropic(tools)
            if converted_tools:
                body["tools"] = converted_tools
                body["tool_choice"] = {"type": "auto"}

        url = f"{self._anthropic_base().rstrip('/')}/v1/messages"
        headers = {
            "x-api-key": self.api_key or "",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        status_code, payload, raw_text = await self._post_json_with_raw(
            url=url,
            headers=headers,
            body=body,
        )
        if status_code != 200:
            raise RuntimeError(self._format_http_error(status_code, payload, raw_text))
        if not isinstance(payload, dict):
            raise RuntimeError(f"HTTP {status_code}: Invalid JSON response: {raw_text[:300]}")
        return self._parse_anthropic(payload)

    async def _chat_via_gemini(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> LLMResponse:
        system_prompt, contents = self._convert_messages_for_gemini(self._sanitize_empty_content(messages))
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max(1, max_tokens),
            },
        }
        if system_prompt:
            body["systemInstruction"] = {"parts": [{"text": system_prompt}]}
        if tools:
            converted_tools = self._convert_tools_for_gemini(tools)
            if converted_tools:
                body["tools"] = converted_tools
                body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}

        model_name = self._normalize_model_for_route(model, "gemini")
        url = f"{self._gemini_base().rstrip('/')}/v1beta/models/{model_name}:generateContent"
        headers = {"Content-Type": "application/json"}
        params = {"key": self.api_key or ""}
        status_code, payload, raw_text = await self._post_json_with_raw(
            url=url,
            headers=headers,
            body=body,
            params=params,
        )
        if status_code != 200:
            raise RuntimeError(self._format_http_error(status_code, payload, raw_text))
        if not isinstance(payload, dict):
            raise RuntimeError(f"HTTP {status_code}: Invalid JSON response: {raw_text[:300]}")
        return self._parse_gemini(payload)

    @staticmethod
    def _format_http_error(status_code: int, payload: Any, raw_text: str) -> str:
        detail: Any = raw_text
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict):
                detail = err.get("message") or err.get("type") or err
            else:
                detail = err or payload
        elif payload is not None:
            detail = payload
        return f"HTTP {status_code}: {detail}"

    def _convert_messages_for_anthropic(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        system_lines: list[str] = []
        converted: list[dict[str, Any]] = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "system":
                text = self._to_text(content)
                if text:
                    system_lines.append(text)
                continue

            if role == "user":
                converted.append({"role": "user", "content": self._to_text(content)})
                continue

            if role == "assistant":
                blocks: list[dict[str, Any]] = []
                text = self._to_text(content)
                if text:
                    blocks.append({"type": "text", "text": text})
                for idx, tc in enumerate(msg.get("tool_calls") or []):
                    fn = tc.get("function") or {}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.get("id") or f"call_{idx}",
                            "name": fn.get("name") or "",
                            "input": self._parse_json_args(fn.get("arguments") or {}),
                        }
                    )
                if blocks:
                    converted.append({"role": "assistant", "content": blocks})
                continue

            if role == "tool":
                converted.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.get("tool_call_id") or "call_0",
                                "content": self._to_text(content),
                            }
                        ],
                    }
                )

        return "\n".join(system_lines).strip(), converted

    @staticmethod
    def _convert_tools_for_anthropic(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for tool in tools:
            fn = (tool.get("function") or {}) if tool.get("type") == "function" else tool
            name = fn.get("name")
            if not name:
                continue
            schema = fn.get("parameters") if isinstance(fn.get("parameters"), dict) else {"type": "object", "properties": {}}
            converted.append(
                {
                    "name": name,
                    "description": fn.get("description") or "",
                    "input_schema": schema,
                }
            )
        return converted

    def _convert_messages_for_gemini(self, messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        system_lines: list[str] = []
        converted: list[dict[str, Any]] = []
        tool_name_by_call_id: dict[str, str] = {}

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            if role == "system":
                text = self._to_text(content)
                if text:
                    system_lines.append(text)
                continue

            if role == "user":
                converted.append({"role": "user", "parts": [{"text": self._to_text(content)}]})
                continue

            if role == "assistant":
                parts: list[dict[str, Any]] = []
                text = self._to_text(content)
                if text:
                    parts.append({"text": text})
                for idx, tc in enumerate(msg.get("tool_calls") or []):
                    fn = tc.get("function") or {}
                    call_id = tc.get("id") or f"call_{idx}"
                    name = fn.get("name") or ""
                    tool_name_by_call_id[call_id] = name
                    parts.append(
                        {
                            "functionCall": {
                                "name": name,
                                "args": self._parse_json_args(fn.get("arguments") or {}),
                            }
                        }
                    )
                if parts:
                    converted.append({"role": "model", "parts": parts})
                continue

            if role == "tool":
                tool_call_id = msg.get("tool_call_id") or ""
                tool_name = tool_name_by_call_id.get(tool_call_id, "tool")
                converted.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": tool_name,
                                    "response": {"result": self._to_text(content)},
                                }
                            }
                        ],
                    }
                )

        return "\n".join(system_lines).strip(), converted

    @staticmethod
    def _convert_tools_for_gemini(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        declarations: list[dict[str, Any]] = []
        for tool in tools:
            fn = (tool.get("function") or {}) if tool.get("type") == "function" else tool
            name = fn.get("name")
            if not name:
                continue
            params = fn.get("parameters") if isinstance(fn.get("parameters"), dict) else {"type": "object", "properties": {}}
            declarations.append(
                {
                    "name": name,
                    "description": fn.get("description") or "",
                    "parameters": params,
                }
            )
        if not declarations:
            return []
        return [{"functionDeclarations": declarations}]

    def _parse_anthropic(self, payload: dict[str, Any]) -> LLMResponse:
        text_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []

        for idx, block in enumerate(payload.get("content") or []):
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text = block.get("text")
                if isinstance(text, str) and text:
                    text_parts.append(text)
            elif block_type == "tool_use":
                tool_calls.append(
                    ToolCallRequest(
                        id=block.get("id") or f"call_{idx}",
                        name=block.get("name") or "",
                        arguments=block.get("input") if isinstance(block.get("input"), dict) else {},
                    )
                )

        stop_reason = (payload.get("stop_reason") or "").lower()
        finish_reason = "length" if "max" in stop_reason else "stop"

        usage_raw = payload.get("usage") or {}
        usage = {
            "prompt_tokens": usage_raw.get("input_tokens", 0),
            "completion_tokens": usage_raw.get("output_tokens", 0),
            "total_tokens": usage_raw.get("input_tokens", 0) + usage_raw.get("output_tokens", 0),
        }

        return LLMResponse(
            content="".join(text_parts) or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )

    def _parse_gemini(self, payload: dict[str, Any]) -> LLMResponse:
        candidates = payload.get("candidates") or []
        candidate = candidates[0] if candidates else {}
        content = candidate.get("content") if isinstance(candidate, dict) else {}
        parts = content.get("parts") if isinstance(content, dict) else []

        text_parts: list[str] = []
        tool_calls: list[ToolCallRequest] = []
        for idx, part in enumerate(parts or []):
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str) and text:
                text_parts.append(text)
            function_call = part.get("functionCall")
            if isinstance(function_call, dict):
                args = function_call.get("args")
                parsed_args = args if isinstance(args, dict) else self._parse_json_args(args)
                tool_calls.append(
                    ToolCallRequest(
                        id=f"gemini_call_{idx}",
                        name=function_call.get("name") or "",
                        arguments=parsed_args,
                    )
                )

        finish_raw = str(candidate.get("finishReason") or "").upper()
        finish_reason = "length" if finish_raw == "MAX_TOKENS" else "stop"

        usage_raw = payload.get("usageMetadata") or {}
        usage = {
            "prompt_tokens": usage_raw.get("promptTokenCount", 0),
            "completion_tokens": usage_raw.get("candidatesTokenCount", 0),
            "total_tokens": usage_raw.get("totalTokenCount", 0),
        }

        return LLMResponse(
            content="".join(text_parts) or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
        )

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

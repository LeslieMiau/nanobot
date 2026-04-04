"""OpenAI-compatible HTTP API server for a fixed nanobot session.

Provides /v1/chat/completions, /v1/models, /v1/voice/ask, and /v1/audio/speech endpoints.
All requests route to a single persistent API session.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from typing import Any

from aiohttp import web
from loguru import logger

from nanobot.utils.runtime import EMPTY_FINAL_RESPONSE_MESSAGE

API_SESSION_KEY = "api:default"
API_CHAT_ID = "default"


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

@web.middleware
async def api_key_middleware(request: web.Request, handler):
    """Check Bearer token or ?key= query param when an API key is configured."""
    api_key: str = request.app.get("api_key", "")
    if not api_key:
        return await handler(request)
    # Skip auth for health check
    if request.path == "/health":
        return await handler(request)
    # Accept key via Authorization header or ?key= query param
    auth = request.headers.get("Authorization", "")
    query_key = request.query.get("key", "")
    if auth == f"Bearer {api_key}" or query_key == api_key:
        return await handler(request)
    return _error_json(401, "Invalid or missing API key", "authentication_error")


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _error_json(status: int, message: str, err_type: str = "invalid_request_error") -> web.Response:
    return web.json_response(
        {"error": {"message": message, "type": err_type, "code": status}},
        status=status,
    )


def _chat_completion_response(content: str, model: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _response_text(value: Any) -> str:
    """Normalize process_direct output to plain assistant text."""
    if value is None:
        return ""
    if hasattr(value, "content"):
        return str(getattr(value, "content") or "")
    return str(value)


_MD_PATTERNS = [
    (re.compile(r"```[\s\S]*?```"), ""),  # code blocks
    (re.compile(r"`([^`]+)`"), r"\1"),  # inline code
    (re.compile(r"\*\*(.+?)\*\*"), r"\1"),  # bold
    (re.compile(r"__(.+?)__"), r"\1"),  # bold alt
    (re.compile(r"\*(.+?)\*"), r"\1"),  # italic
    (re.compile(r"_(.+?)_"), r"\1"),  # italic alt
    (re.compile(r"~~(.+?)~~"), r"\1"),  # strikethrough
    (re.compile(r"^#{1,6}\s+", re.MULTILINE), ""),  # headings
    (re.compile(r"^\s*[-*+]\s+", re.MULTILINE), "- "),  # list items
    (re.compile(r"\[([^\]]+)\]\([^)]+\)"), r"\1"),  # links
    (re.compile(r"!\[([^\]]*)\]\([^)]+\)"), r"\1"),  # images
]


def _strip_markdown(text: str) -> str:
    """Strip markdown formatting for voice-friendly plain text."""
    for pattern, replacement in _MD_PATTERNS:
        text = pattern.sub(replacement, text)
    return text.strip()


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

async def handle_chat_completions(request: web.Request) -> web.Response:
    """POST /v1/chat/completions"""

    # --- Parse body ---
    try:
        body = await request.json()
    except Exception:
        return _error_json(400, "Invalid JSON body")

    messages = body.get("messages")
    if not isinstance(messages, list) or len(messages) != 1:
        return _error_json(400, "Only a single user message is supported")

    # Stream not yet supported
    if body.get("stream", False):
        return _error_json(400, "stream=true is not supported yet. Set stream=false or omit it.")

    message = messages[0]
    if not isinstance(message, dict) or message.get("role") != "user":
        return _error_json(400, "Only a single user message is supported")
    user_content = message.get("content", "")
    if isinstance(user_content, list):
        # Multi-modal content array — extract text parts
        user_content = " ".join(
            part.get("text", "") for part in user_content if part.get("type") == "text"
        )

    agent_loop = request.app["agent_loop"]
    timeout_s: float = request.app.get("request_timeout", 120.0)
    model_name: str = request.app.get("model_name", "nanobot")
    if (requested_model := body.get("model")) and requested_model != model_name:
        return _error_json(400, f"Only configured model '{model_name}' is available")

    session_key = f"api:{body['session_id']}" if body.get("session_id") else API_SESSION_KEY
    session_locks: dict[str, asyncio.Lock] = request.app["session_locks"]
    session_lock = session_locks.setdefault(session_key, asyncio.Lock())

    logger.info("API request session_key={} content={}", session_key, user_content[:80])

    _FALLBACK = EMPTY_FINAL_RESPONSE_MESSAGE

    try:
        async with session_lock:
            try:
                response = await asyncio.wait_for(
                    agent_loop.process_direct(
                        content=user_content,
                        session_key=session_key,
                        channel="api",
                        chat_id=API_CHAT_ID,
                    ),
                    timeout=timeout_s,
                )
                response_text = _response_text(response)

                if not response_text or not response_text.strip():
                    logger.warning(
                        "Empty response for session {}, retrying",
                        session_key,
                    )
                    retry_response = await asyncio.wait_for(
                        agent_loop.process_direct(
                            content=user_content,
                            session_key=session_key,
                            channel="api",
                            chat_id=API_CHAT_ID,
                        ),
                        timeout=timeout_s,
                    )
                    response_text = _response_text(retry_response)
                    if not response_text or not response_text.strip():
                        logger.warning(
                            "Empty response after retry for session {}, using fallback",
                            session_key,
                        )
                        response_text = _FALLBACK

            except asyncio.TimeoutError:
                return _error_json(504, f"Request timed out after {timeout_s}s")
            except Exception:
                logger.exception("Error processing request for session {}", session_key)
                return _error_json(500, "Internal server error", err_type="server_error")
    except Exception:
        logger.exception("Unexpected API lock error for session {}", session_key)
        return _error_json(500, "Internal server error", err_type="server_error")

    return web.json_response(_chat_completion_response(response_text, model_name))


async def handle_voice_ask(request: web.Request) -> web.Response:
    """POST/GET /v1/voice/ask — voice Q&A endpoint.

    POST: {"text": "question", "speaker": "name"}
    GET:  ?text=question&speaker=name

    Returns {"reply": "plain-text answer", "end_conversation": false}.
    """
    if request.method == "GET":
        user_text = request.query.get("text", "").strip()
        body = dict(request.query)
    else:
        content_type = request.content_type or ""
        if "form" in content_type:
            form_data = await request.post()
            body = dict(form_data)
        else:
            try:
                body = await request.json()
            except Exception:
                return _error_json(400, "Invalid JSON body")
        user_text = body.get("text", "").strip()

    if not user_text:
        return _error_json(400, "Missing 'text' field")

    # Speaker / session identification — compatible with ClawPod
    speaker = body.get("speaker", "") or body.get("session_id", "voice")
    session_key = f"api:{speaker}"

    agent_loop = request.app["agent_loop"]
    timeout_s: float = request.app.get("request_timeout", 120.0)
    session_locks: dict[str, asyncio.Lock] = request.app["session_locks"]
    session_lock = session_locks.setdefault(session_key, asyncio.Lock())

    logger.info("Voice ask speaker={} text={}", speaker, user_text[:80])

    try:
        async with session_lock:
            try:
                response = await asyncio.wait_for(
                    agent_loop.process_direct(
                        content=user_text,
                        session_key=session_key,
                        channel="api",
                        chat_id=API_CHAT_ID,
                    ),
                    timeout=timeout_s,
                )
                response_text = _response_text(response)
                if not response_text or not response_text.strip():
                    response_text = EMPTY_FINAL_RESPONSE_MESSAGE
            except asyncio.TimeoutError:
                return _error_json(504, f"Request timed out after {timeout_s}s")
            except Exception:
                logger.exception("Error processing voice request for speaker {}", speaker)
                return _error_json(500, "Internal server error", err_type="server_error")
    except Exception:
        logger.exception("Unexpected voice API lock error for speaker {}", speaker)
        return _error_json(500, "Internal server error", err_type="server_error")

    plain_text = _strip_markdown(response_text)

    # Detect end-of-conversation signals in the response
    end_phrases = {"再见", "拜拜", "下次见", "goodbye", "bye"}
    end_conversation = any(p in plain_text.lower() for p in end_phrases)

    return web.json_response({
        "reply": plain_text,
        "end_conversation": end_conversation,
    })


async def handle_audio_speech(request: web.Request) -> web.Response:
    """POST /v1/audio/speech — text-to-speech endpoint.

    Accepts {"input": "text to speak", "voice": "alloy", "model": "tts-1"}
    and returns audio/mpeg bytes.
    """
    try:
        body = await request.json()
    except Exception:
        return _error_json(400, "Invalid JSON body")

    text = body.get("input", "").strip()
    if not text:
        return _error_json(400, "Missing 'input' field")

    tts_config = request.app.get("tts_config")
    voice = body.get("voice", tts_config.voice if tts_config else "alloy")
    model = body.get("model", tts_config.model if tts_config else "tts-1")

    try:
        from nanobot.providers.tts import get_tts_provider

        provider = get_tts_provider(tts_config, request.app.get("nanobot_config"))
        audio_bytes = await provider.synthesize(text, voice=voice, model=model)
    except ValueError as e:
        return _error_json(400, str(e))
    except Exception:
        logger.exception("TTS synthesis failed")
        return _error_json(500, "TTS synthesis failed", err_type="server_error")

    return web.Response(
        body=audio_bytes,
        content_type="audio/mpeg",
        headers={"Content-Disposition": 'inline; filename="speech.mp3"'},
    )


async def handle_models(request: web.Request) -> web.Response:
    """GET /v1/models"""
    model_name = request.app.get("model_name", "nanobot")
    return web.json_response({
        "object": "list",
        "data": [
            {
                "id": model_name,
                "object": "model",
                "created": 0,
                "owned_by": "nanobot",
            }
        ],
    })


async def handle_health(request: web.Request) -> web.Response:
    """GET /health"""
    return web.json_response({"status": "ok"})


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    agent_loop,
    model_name: str = "nanobot",
    request_timeout: float = 120.0,
    api_key: str = "",
    tts_config=None,
    nanobot_config=None,
) -> web.Application:
    """Create the aiohttp application.

    Args:
        agent_loop: An initialized AgentLoop instance.
        model_name: Model name reported in responses.
        request_timeout: Per-request timeout in seconds.
        api_key: Bearer token for authentication. Empty string disables auth.
        tts_config: TTSConfig instance for /v1/audio/speech endpoint.
        nanobot_config: Root Config instance for provider key fallback.
    """
    app = web.Application(middlewares=[api_key_middleware])
    app["agent_loop"] = agent_loop
    app["model_name"] = model_name
    app["request_timeout"] = request_timeout
    app["api_key"] = api_key
    app["tts_config"] = tts_config
    app["nanobot_config"] = nanobot_config
    app["session_locks"] = {}  # per-user locks, keyed by session_key

    app.router.add_post("/v1/chat/completions", handle_chat_completions)
    app.router.add_post("/v1/voice/ask", handle_voice_ask)
    app.router.add_get("/v1/voice/ask", handle_voice_ask)
    app.router.add_post("/v1/audio/speech", handle_audio_speech)
    app.router.add_get("/v1/models", handle_models)
    app.router.add_get("/health", handle_health)
    return app

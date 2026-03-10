"""Image generation staging and confirmation helpers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from nanobot.bus.events import InboundMessage, OutboundMessage

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop
    from nanobot.session.manager import Session


class ImageFlowController:
    """Manage staged image prompts for one agent runtime."""

    QUEUE_KEY = "image_generation_queue"

    def __init__(self, loop: AgentLoop):
        self.loop = loop

    def _get_image_queue(self, session: Session) -> dict[str, Any]:
        queue = session.metadata.get(self.QUEUE_KEY)
        if not isinstance(queue, dict):
            queue = {"items": []}
            session.metadata[self.QUEUE_KEY] = queue
        items = queue.get("items")
        if not isinstance(items, list):
            queue["items"] = []
        return queue

    @staticmethod
    def _current_image_index(items: list[dict[str, Any]]) -> int | None:
        for idx, item in enumerate(items):
            if item.get("status") == "pending":
                return idx
        return None

    def _format_image_preview(self, item: dict[str, Any], *, position: int, total: int) -> str:
        title = item.get("title") or f"Image {position}/{total}"
        platform = item.get("platform") or "generic"
        role_name = item.get("role_name") or "TradingCat"
        overlay_text = item.get("overlay_text") or "(none)"
        output_path = item.get("output_path") or ""
        aspect_ratio = item.get("aspect_ratio") or ""
        size = item.get("size") or ""
        return (
            f"[Image prompt {position}/{total}] {title}\n"
            f"Platform: {platform}\n"
            f"Role: {role_name}\n"
            f"Overlay text: {overlay_text}\n"
            f"Aspect ratio: {aspect_ratio or '(default)'}\n"
            f"Size: {size or '(default)'}\n"
            f"Output path: `{output_path}`\n\n"
            "Prompt:\n"
            f"```text\n{item.get('prompt', '')}\n```\n\n"
            "Reply `/image-confirm` to generate this image, "
            "`/image-edit <feedback>` to revise the prompt, or `/image-skip` to skip it."
        )

    async def stage_request(self, payload: dict[str, Any]) -> str:
        channel = str(payload.get("channel") or "").strip()
        chat_id = str(payload.get("chat_id") or "").strip()
        if not channel or not chat_id:
            return "Error: no active session context for image staging"

        session = self.loop.sessions.get_or_create(f"{channel}:{chat_id}")
        queue = self._get_image_queue(session)
        items: list[dict[str, Any]] = queue["items"]
        item = {
            "content_pack_id": payload.get("content_pack_id") or "",
            "card_index": payload.get("card_index") or len(items) + 1,
            "title": payload.get("title") or "",
            "overlay_text": payload.get("overlay_text") or "",
            "role_name": payload.get("role_name") or "TradingCat",
            "platform": payload.get("platform") or "xiaohongshu",
            "prompt": payload.get("prompt") or "",
            "base_prompt": payload.get("prompt") or "",
            "size": payload.get("size") or "",
            "aspect_ratio": payload.get("aspect_ratio") or "",
            "style_preset": payload.get("style_preset") or "",
            "negative_prompt": payload.get("negative_prompt") or "",
            "output_path": payload.get("output_path") or "",
            "status": "pending",
        }
        items.append(item)
        self.loop.sessions.save(session)

        current_idx = self._current_image_index(items)
        if current_idx == len(items) - 1:
            return self._format_image_preview(item, position=current_idx + 1, total=len(items))
        staged_label = item["title"] or f"card {item['card_index']}"
        return f"Staged image {len(items)}/{len(items)}: {staged_label}"

    async def handle_confirm(self, msg: InboundMessage, session: Session) -> OutboundMessage:
        queue = self._get_image_queue(session)
        items: list[dict[str, Any]] = queue["items"]
        idx = self._current_image_index(items)
        if idx is None:
            session.metadata.pop(self.QUEUE_KEY, None)
            self.loop.sessions.save(session)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="No pending image prompt to confirm.",
            )

        item = items[idx]
        tool = self.loop.tools.get("image_generate")
        if tool is None:
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="Image generation tool is not available.",
            )
        result = await tool.execute(
            action="generate",
            prompt=item["prompt"],
            output_path=item["output_path"],
            size=item.get("size") or None,
            aspect_ratio=item.get("aspect_ratio") or None,
            style_preset=item.get("style_preset") or None,
            negative_prompt=item.get("negative_prompt") or None,
        )
        if result.startswith("Error:"):
            return OutboundMessage(channel=msg.channel, chat_id=msg.chat_id, content=result)

        payload = json.loads(result)
        item["status"] = "generated"
        item["generated_path"] = payload.get("file_path") or ""
        item["model"] = payload.get("model") or ""
        item["provider"] = payload.get("provider") or ""

        next_idx = self._current_image_index(items)
        if next_idx is None:
            session.metadata.pop(self.QUEUE_KEY, None)
            self.loop.sessions.save(session)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=(
                    f"Generated image {idx + 1}/{len(items)}: `{payload.get('file_path', '')}`\n"
                    "All staged images are processed."
                ),
            )

        self.loop.sessions.save(session)
        next_item = items[next_idx]
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=(
                f"Generated image {idx + 1}/{len(items)}: `{payload.get('file_path', '')}`\n\n"
                + self._format_image_preview(next_item, position=next_idx + 1, total=len(items))
            ),
        )

    def handle_edit(self, msg: InboundMessage, session: Session, feedback: str) -> OutboundMessage:
        queue = self._get_image_queue(session)
        items: list[dict[str, Any]] = queue["items"]
        idx = self._current_image_index(items)
        if idx is None:
            session.metadata.pop(self.QUEUE_KEY, None)
            self.loop.sessions.save(session)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="No pending image prompt to edit.",
            )
        if not feedback.strip():
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="Usage: `/image-edit <feedback>`",
            )

        item = items[idx]
        base_prompt = item.get("base_prompt") or item.get("prompt") or ""
        item["base_prompt"] = base_prompt
        item["prompt"] = f"{base_prompt}\n\nRevision request: {feedback.strip()}"
        self.loop.sessions.save(session)
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=self._format_image_preview(item, position=idx + 1, total=len(items)),
        )

    def handle_skip(self, msg: InboundMessage, session: Session) -> OutboundMessage:
        queue = self._get_image_queue(session)
        items: list[dict[str, Any]] = queue["items"]
        idx = self._current_image_index(items)
        if idx is None:
            session.metadata.pop(self.QUEUE_KEY, None)
            self.loop.sessions.save(session)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="No pending image prompt to skip.",
            )

        items[idx]["status"] = "skipped"
        next_idx = self._current_image_index(items)
        if next_idx is None:
            session.metadata.pop(self.QUEUE_KEY, None)
            self.loop.sessions.save(session)
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=f"Skipped image {idx + 1}/{len(items)}. No more staged images remain.",
            )

        self.loop.sessions.save(session)
        next_item = items[next_idx]
        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=(
                f"Skipped image {idx + 1}/{len(items)}.\n\n"
                + self._format_image_preview(next_item, position=next_idx + 1, total=len(items))
            ),
        )

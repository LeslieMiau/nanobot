"""Token Guard policy and state helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nanobot.agent.model_selection import ModelSelectionController

if TYPE_CHECKING:
    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.events import InboundMessage
    from nanobot.session.manager import Session


@dataclass(frozen=True)
class TokenGuardAssessment:
    mode: str
    total_score: int
    raw_risk: str
    final_risk: str
    raw_range: str
    effective_range: str
    cache_friendliness: str
    effective_increment: str
    risk_tags: list[str]
    waste_tags: list[str]
    drivers: list[str]
    alternatives: list[str]
    hard_triggered: bool = False


class TokenGuardController:
    """Manage token guard state, interception, and reporting."""

    def __init__(self, loop: AgentLoop):
        self.loop = loop

    @staticmethod
    def estimate_tokens(messages: list[dict[str, Any]]) -> int:
        """Estimate token usage from message payload size."""
        total_chars = 0

        def walk(value: Any) -> None:
            nonlocal total_chars
            if isinstance(value, str):
                total_chars += len(value)
                return
            if isinstance(value, dict):
                for nested in value.values():
                    walk(nested)
                return
            if isinstance(value, list):
                for nested in value:
                    walk(nested)

        walk(messages)
        return max(1, (total_chars + 2) // 3)

    @staticmethod
    def band_from_score(total: int) -> tuple[str, str]:
        if total <= 5:
            return "minimal", "<2k"
        if total <= 9:
            return "small", "2k-8k"
        if total <= 14:
            return "medium", "8k-25k"
        if total <= 19:
            return "large", "25k-60k"
        return "extreme", "60k+"

    @staticmethod
    def band_index(risk: str) -> int:
        return {"minimal": 0, "small": 1, "medium": 2, "large": 3, "extreme": 4}[risk]

    @classmethod
    def risk_from_index(cls, index: int) -> str:
        return ("minimal", "small", "medium", "large", "extreme")[max(0, min(4, index))]

    @classmethod
    def risk_from_budget_k(cls, budget_k: int) -> str:
        if budget_k <= 2:
            return "minimal"
        if budget_k <= 8:
            return "small"
        if budget_k <= 25:
            return "medium"
        if budget_k <= 60:
            return "large"
        return "extreme"

    @staticmethod
    def flatten_message_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        text = item.get("text")
                        if isinstance(text, str):
                            parts.append(text)
                    elif item.get("type") == "image_url":
                        parts.append("[image]")
            return "\n".join(parts)
        return ""

    def state(self, session: Session) -> dict[str, Any]:
        raw = session.metadata.get(self.loop._TOKEN_GUARD_STATE_KEY)
        state = raw if isinstance(raw, dict) else {}

        default_mode = str(self.loop.token_guard.default_mode or "on").strip().lower()
        if default_mode not in self.loop._TOKEN_GUARD_MODES:
            default_mode = "on"
        mode = str(state.get("mode") or default_mode).strip().lower()
        if mode not in self.loop._TOKEN_GUARD_MODES:
            mode = default_mode

        try:
            budget_k = int(state.get("budget_k", self.loop.token_guard.default_budget_k))
        except (TypeError, ValueError):
            budget_k = int(self.loop.token_guard.default_budget_k)
        budget_k = max(1, budget_k)

        pending_message = state.get("pending_message")
        if not isinstance(pending_message, str) or not pending_message.strip():
            pending_message = None

        return {
            "mode": mode,
            "budget_k": budget_k,
            "pending_message": pending_message,
        }

    def save_state(self, session: Session, state: dict[str, Any]) -> None:
        pending_message = state.get("pending_message")
        session.metadata[self.loop._TOKEN_GUARD_STATE_KEY] = {
            "mode": state["mode"],
            "budget_k": int(state["budget_k"]),
            "pending_message": pending_message if isinstance(pending_message, str) and pending_message.strip() else None,
        }
        self.loop.sessions.save(session)

    def clear_pending(self, session: Session, *, save: bool) -> None:
        state = self.state(session)
        if state.get("pending_message") is None:
            return
        state["pending_message"] = None
        if save:
            self.save_state(session, state)
        else:
            session.metadata[self.loop._TOKEN_GUARD_STATE_KEY] = {
                "mode": state["mode"],
                "budget_k": state["budget_k"],
                "pending_message": None,
            }

    @staticmethod
    def parse_control(content: str) -> tuple[str, str | int] | None:
        raw = content.strip()
        if not raw:
            return None
        lowered = raw.lower()
        if match := re.fullmatch(r"token\s*guard\s*:\s*(off|on|strict|relaxed)", lowered):
            return "mode", match.group(1)
        if match := re.fullmatch(r"token\s*budget\s*:\s*(\d+)\s*k", lowered):
            return "budget", int(match.group(1))
        if lowered in {"stop blocking", "stop warning"}:
            return "mode", "relaxed"
        if lowered == "just do it":
            return "mode", "off"
        return None

    def is_proceed_message(self, content: str) -> bool:
        return content.strip().lower() in self.loop._TOKEN_GUARD_PROCEED_ALIASES

    def is_cancel_message(self, content: str) -> bool:
        return content.strip().lower() in self.loop._TOKEN_GUARD_CANCEL_ALIASES

    def classify_task_topic(self, text: str) -> str:
        lowered = text.lower()
        if self.loop._looks_like_coding_request(text):
            return "code"
        if any(token in lowered for token in ("doc", "docs", "readme", "documentation", "文档", "说明")):
            return "doc"
        if any(token in lowered for token in ("image", "images", "picture", "图片", "截图", "pdf")):
            return "image"
        if any(token in lowered for token in ("analysis", "analyze", "review", "总结", "分析", "评估")):
            return "analysis"
        return "other"

    @staticmethod
    def risk_label(risk: str) -> str:
        return {
            "minimal": "低风险",
            "small": "低风险",
            "medium": "中风险",
            "large": "大",
            "extreme": "极高",
        }[risk]

    @staticmethod
    def cache_label(level: str) -> str:
        return {"high": "高", "medium": "中", "low": "低"}[level]

    @staticmethod
    def effective_increment_label(risk: str) -> str:
        return {
            "minimal": "低",
            "small": "低",
            "medium": "中",
            "large": "高",
            "extreme": "极高",
        }[risk]

    def assess(
        self,
        *,
        session: Session,
        history: list[dict[str, Any]],
        msg: InboundMessage,
        coding_enabled: bool,
        mode: str,
        parsed_cmd: str,
    ) -> TokenGuardAssessment:
        lowered = msg.content.lower()
        budget_k = self.state(session)["budget_k"]
        history_tokens = self.estimate_tokens(history)
        current_tokens = self.estimate_tokens(
            [{"role": "user", "content": {"text": msg.content, "media": ["[attachment]"] * len(msg.media or [])}}]
        )
        media_count = len(msg.media or [])
        user_turns = sum(1 for item in history if item.get("role") == "user")

        if current_tokens < 250:
            signal_a = 0
        elif current_tokens < 1_200:
            signal_a = 1
        elif current_tokens < 4_000:
            signal_a = 2
        else:
            signal_a = 3

        mentioned_heavy_files = any(token in lowered for token in ("pdf", "images", "screenshots", "截图", "图片", "附件"))
        if media_count == 0 and not mentioned_heavy_files:
            signal_b = 0
        elif media_count <= 2:
            signal_b = 1
        elif media_count <= 6 or mentioned_heavy_files:
            signal_b = 2
        else:
            signal_b = 3

        repo_wide = any(
            token in lowered
            for token in (
                "repo-wide", "repository-wide", "whole repo", "entire repo", "entire project", "all files",
                "整个仓库", "整个项目", "全仓", "所有文件", "全项目",
            )
        )
        multi_file = repo_wide or self.loop._looks_like_large_change_request(msg.content) or any(
            token in lowered for token in ("across files", "multiple files", "many files", "多文件", "跨文件")
        )
        if repo_wide:
            signal_c = 3
        elif multi_file:
            signal_c = 2
        elif coding_enabled or self.loop._looks_like_path_or_code(msg.content):
            signal_c = 1
        else:
            signal_c = 0

        process_markers = [
            "search", "scan", "grep", "read", "edit", "patch", "modify", "test", "verify", "debug", "trace",
            "搜索", "扫描", "读取", "修改", "补丁", "测试", "验证", "排查", "重构",
        ]
        process_hits = sum(1 for marker in process_markers if marker in lowered)
        if (signal_c >= 2 and process_hits >= 3) or ("step by step" in lowered) or ("逐步" in lowered):
            signal_d = 3
        elif process_hits >= 2 or (coding_enabled and signal_c >= 2):
            signal_d = 2
        elif coding_enabled or process_hits >= 1:
            signal_d = 1
        else:
            signal_d = 0

        exhaustive = any(
            token in lowered
            for token in (
                "exhaustive", "every", "everything", "list all", "all possible", "item by item",
                "逐项", "穷举", "全量", "全部列出", "详细列出", "所有可能",
            )
        )
        detailed = exhaustive or any(
            token in lowered for token in ("detailed", "deep dive", "full report", "详细", "完整报告", "深入")
        )
        if exhaustive and signal_c >= 2:
            signal_e = 3
        elif detailed:
            signal_e = 2
        elif any(token in lowered for token in ("explain", "summary", "说明", "总结")):
            signal_e = 1
        else:
            signal_e = 0

        if history_tokens < 4_000 and user_turns < 8:
            signal_f = 0
        elif history_tokens < 12_000 and user_turns < 20:
            signal_f = 1
        elif history_tokens < 30_000 and user_turns < 50:
            signal_f = 2
        else:
            signal_f = 3

        risk_tags: list[str] = []
        waste_tags: list[str] = []

        previous_user_text = ""
        for item in reversed(history):
            if item.get("role") == "user":
                previous_user_text = self.flatten_message_text(item.get("content"))
                break
        current_topic = self.classify_task_topic(msg.content)
        previous_topic = self.classify_task_topic(previous_user_text) if previous_user_text else "other"

        signal_g = 0
        if signal_f > 0 and previous_topic not in {"other", current_topic}:
            signal_g = 2 if signal_f >= 2 else 1
            waste_tags.append("CROSS_THEME")
        if signal_f >= 2 and signal_a >= 2 and any(
            token in lowered for token in ("rules", "instructions", "requirements", "policy", "规则", "要求", "约束")
        ):
            signal_g = max(signal_g, 2)
            waste_tags.append("REPEATED_RULES")
        if signal_f >= 3 and signal_a >= 2:
            signal_g = max(signal_g, 3)

        tool_categories = 0
        if any(token in lowered for token in ("web", "browse", "search online", "google", "internet", "网页", "联网")):
            tool_categories += 1
            risk_tags.append("HEAVY_BASH_WEB")
        if any(token in lowered for token in ("bash", "shell", "terminal", "command", "git ", "pytest", "日志", "命令行")):
            tool_categories += 1
            if "HEAVY_BASH_WEB" not in risk_tags:
                risk_tags.append("HEAVY_BASH_WEB")
        if any(token in lowered for token in ("mcp", "server", "servers")):
            tool_categories += 1
            risk_tags.append("HEAVY_MCP")
        if any(token in lowered for token in ("subagent", "agent loop", "spawn", "子代理")):
            tool_categories += 1
            risk_tags.append("SUBAGENT_HEAVY")
        if tool_categories >= 3:
            signal_h = 3
        elif tool_categories == 2:
            signal_h = 2
        elif tool_categories == 1:
            signal_h = 1
        else:
            signal_h = 0

        signal_i = 0
        switch_tags = 0
        if parsed_cmd == "/model" or ModelSelectionController.parse_natural_model_switch(msg.content):
            signal_i = max(signal_i, 2)
            switch_tags += 1
            risk_tags.append("MODEL_SWITCH")
        if any(token in lowered for token in ("thinking mode", "reasoning mode", "深度思考", "推理模式")):
            signal_i = max(signal_i, 2)
            switch_tags += 1
            risk_tags.append("THINKING_SWITCH")
        if any(token in lowered for token in ("switch tools", "tool strategy", "改用 mcp", "改用 web", "换工具")):
            signal_i = max(signal_i, 1)
            switch_tags += 1
            risk_tags.append("TOOL_STRATEGY_SWITCH")
        if switch_tags >= 2:
            signal_i = max(signal_i, 3)

        if signal_f >= 2:
            risk_tags.append("LONG_SESSION")
        if signal_c >= 3:
            risk_tags.append("REPO_WIDE")
        if signal_d >= 3:
            risk_tags.append("TOOL_LOOP")
        if signal_e >= 2:
            risk_tags.append("BIG_OUTPUT")
        if signal_b >= 2:
            risk_tags.append("BIG_FILES")

        total = signal_a + signal_b + signal_c + signal_d + signal_e + signal_f + signal_g + signal_h + signal_i
        raw_risk, raw_range = self.band_from_score(total)

        cache_penalty = signal_f + signal_g + signal_i
        if cache_penalty <= 2:
            cache_friendliness = "high"
        elif cache_penalty <= 5:
            cache_friendliness = "medium"
        else:
            cache_friendliness = "low"

        hard_triggered = any(
            (
                signal_c >= 2 and signal_d >= 3,
                signal_b >= 3,
                signal_f >= 2 and signal_c >= 3,
                signal_i >= 2 and signal_f >= 2,
                switch_tags >= 2,
                signal_e >= 3 and signal_c >= 2,
                signal_h >= 3 and signal_d >= 2,
            )
        )

        final_index = self.band_index(raw_risk)
        budget_pressure = False
        if hard_triggered:
            final_index = self.band_index("extreme")
        else:
            if raw_risk in {"large", "extreme"} and cache_friendliness == "high":
                final_index -= 1
            if raw_risk in {"medium", "large", "extreme"} and cache_friendliness == "low":
                final_index += 1
            if switch_tags > 0:
                final_index += 1
            if mode == "strict":
                final_index += 1
            elif mode == "relaxed":
                final_index -= 1
            budget_index = self.band_index(self.risk_from_budget_k(budget_k))
            if final_index > budget_index or (final_index == budget_index and budget_k <= 12 and final_index >= 2):
                final_index += 1
                budget_pressure = True
        final_risk = self.risk_from_index(final_index)
        _, effective_range = self.band_from_score(
            {self.risk_from_index(i): score for i, score in enumerate((0, 6, 10, 15, 20))}[final_risk]
        )

        driver_candidates: list[tuple[int, str]] = []
        if signal_f >= 2:
            driver_candidates.append((signal_f, f"当前会话已经偏长，历史上下文粗估约 {history_tokens} tokens。"))
        if signal_c >= 3:
            driver_candidates.append((signal_c + 1, "请求范围接近仓库级或项目级。"))
        elif signal_c == 2:
            driver_candidates.append((signal_c, "请求已经扩展到多文件或多模块范围。"))
        if signal_d >= 2:
            driver_candidates.append((signal_d, "任务很可能进入 search-read-edit-test 这类多步工具循环。"))
        if signal_h >= 2:
            driver_candidates.append((signal_h, "Bash/Web/MCP 等高开销工具链暴露较多。"))
        if signal_e >= 2:
            driver_candidates.append((signal_e, "你要求的输出偏长或偏全量。"))
        if signal_i >= 2:
            driver_candidates.append((signal_i, "当前请求包含模型、思考模式或工具策略切换。"))
        if signal_a >= 2:
            driver_candidates.append((signal_a, f"当前输入本身已经较长，粗估约 {current_tokens} tokens。"))
        if signal_g >= 2:
            driver_candidates.append((signal_g, "当前前缀缓存友好度较低，重复成本更高。"))
        if budget_pressure:
            driver_candidates.append((3, f"当前 TokenBudget 只有 {budget_k}k，和预计体量已经开始相撞。"))
        drivers = [text for _, text in sorted(driver_candidates, key=lambda item: item[0], reverse=True)[:3]]
        if not drivers:
            drivers = ["当前请求没有明显的高成本模式。"]

        alternatives: list[str] = []
        if signal_c >= 2:
            alternatives.append("先把范围缩到一个目录、模块或文件集，再逐批推进。")
        if signal_f >= 2:
            alternatives.append("考虑先开新会话，或者先压缩上下文后再继续。")
        if signal_h >= 2:
            alternatives.append("先用 grep/read 缩小范围，避免把大段工具输出重新喂回上下文。")
        if signal_e >= 2:
            alternatives.append("先给结论和补丁计划，详细展开按需追加。")
        if not alternatives:
            alternatives = [
                "先限定问题表面，再决定是否需要扩大范围。",
                "先输出结论和执行计划，细节按需展开。",
                "先验证最高价值的子集，再决定是否继续扩展。",
            ]

        return TokenGuardAssessment(
            mode=mode,
            total_score=total,
            raw_risk=raw_risk,
            final_risk=final_risk,
            raw_range=raw_range,
            effective_range=effective_range,
            cache_friendliness=cache_friendliness,
            effective_increment=self.effective_increment_label(final_risk),
            risk_tags=sorted(set(risk_tags)),
            waste_tags=sorted(set(waste_tags)),
            drivers=drivers,
            alternatives=alternatives[:3],
            hard_triggered=hard_triggered,
        )

    def intercept_message(self, state: dict[str, Any], assessment: TokenGuardAssessment) -> str:
        risk_tags = assessment.risk_tags or ["NONE"]
        return (
            "⚠️ Token Guard 拦截\n\n"
            f"风险等级：{self.risk_label(assessment.final_risk)}\n"
            f"缓存友好度：{self.cache_label(assessment.cache_friendliness)}\n"
            f"预计有效新增：{assessment.effective_increment}\n"
            f"你的 TokenBudget：{state['budget_k']}k，仅供参考\n\n"
            "主要耗费点（前 3 项）：\n"
            f"1. {assessment.drivers[0]}\n"
            f"2. {assessment.drivers[1] if len(assessment.drivers) > 1 else assessment.drivers[0]}\n"
            f"3. {assessment.drivers[2] if len(assessment.drivers) > 2 else assessment.drivers[-1]}\n\n"
            "已识别风险标签：\n"
            f"{', '.join(risk_tags)}\n\n"
            "推荐低成本替代方案：\n"
            f"- {assessment.alternatives[0]}\n"
            f"- {assessment.alternatives[1] if len(assessment.alternatives) > 1 else assessment.alternatives[0]}\n"
            f"- {assessment.alternatives[2] if len(assessment.alternatives) > 2 else assessment.alternatives[-1]}\n\n"
            "继续方式：\n"
            "- 回复「继续 / 批准 / ok / proceed」= 仅放行本次原任务\n"
            "- 或直接给一个缩小范围、降低浪费的新指令"
        )

    def append_estimate(
        self,
        content: str | None,
        assessment: TokenGuardAssessment,
    ) -> str | None:
        if not content:
            return content
        silent_below = str(getattr(self.loop.token_guard, "silent_below", "large")).strip().lower()
        if silent_below not in {"minimal", "small", "medium", "large", "extreme"}:
            silent_below = "large"
        if self.band_index(assessment.final_risk) < self.band_index(silent_below):
            return content
        risk = "低风险" if assessment.final_risk in {"minimal", "small"} else "中风险"
        line = (
            f"Token Guard：原始体量 ≈ {assessment.raw_range}，缓存友好度 "
            f"{self.cache_label(assessment.cache_friendliness)}，预计有效新增 ≈ "
            f"{assessment.effective_range} tokens（{risk}，粗估）"
        )
        return content.rstrip() + "\n\n" + line

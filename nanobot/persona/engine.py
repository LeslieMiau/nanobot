"""Persona engine for runtime style and output controls."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from nanobot.providers.base import LLMProvider

if TYPE_CHECKING:
    from nanobot.config.schema import PersonaConfig


class PersonaEngine:
    """Applies persona-specific runtime hints, temperature, and output normalization."""

    _SCENE_CHAT = "chat"
    _SCENE_TASK = "task"
    _SCENE_HIGH_RISK = "high_risk"

    _HIGH_RISK_KEYWORDS = (
        "医疗", "医药", "手术", "处方", "急救", "症状", "诊断",
        "法律", "律师", "起诉", "合同", "法院", "财务", "投资",
        "股票", "期权", "杠杆", "税务", "报税", "安全漏洞", "勒索",
    )
    _TASK_KEYWORDS = (
        "怎么", "如何", "帮我", "请你", "修复", "排查", "报错", "错误", "error",
        "bug", "命令", "配置", "安装", "运行", "代码", "脚本", "实现", "部署",
    )

    _TRAD_TO_SIMPLIFIED_MAP = {
        "東": "东", "賴": "赖", "錯": "错", "這": "这", "樣": "样", "說": "说", "話": "话",
        "個": "个", "麼": "么", "還": "还", "嗎": "吗", "覺": "觉", "對": "对", "給": "给",
        "幫": "帮", "為": "为", "來": "来", "會": "会", "時": "时", "讓": "让", "點": "点",
        "買": "买", "賺": "赚", "應": "应", "該": "该", "醫": "医", "療": "疗", "財": "财",
        "務": "务", "風": "风", "險": "险", "請": "请", "問": "问", "沒": "没", "關": "关",
        "係": "系", "開": "开", "裡": "里", "長": "长", "種": "种", "實": "实", "現": "现",
        "體": "体", "們": "们", "與": "与", "後": "后", "發": "发", "學": "学", "習": "习",
        "簡": "简", "語": "语", "氣": "气", "盡": "尽", "經": "经", "變": "变", "態": "态",
        "壞": "坏", "愛": "爱", "熱": "热", "貓": "猫", "擔": "担", "憂": "忧", "樂": "乐",
        "驚": "惊", "聽": "听", "頭": "头", "張": "张", "優": "优", "邊": "边", "舊": "旧",
        "寫": "写", "處": "处", "間": "间", "難": "难", "備": "备", "調": "调", "試": "试",
        "誤": "误", "證": "证", "產": "产", "業": "业", "價": "价", "錢": "钱", "線": "线",
        "網": "网", "絡": "络", "機": "机", "終": "终", "歸": "归", "達": "达", "認": "认",
        "確": "确", "嚴": "严", "謹": "谨", "轉": "转", "換": "换", "遞": "递", "專": "专",
        "綜": "综", "複": "复", "雜": "杂", "門": "门",
    }
    _TRAD_HINT_CHARS = set(_TRAD_TO_SIMPLIFIED_MAP.keys())

    def __init__(self, persona_config: "PersonaConfig | None"):
        self.config = persona_config
        self._quote_entries = self._load_quote_entries()

    @property
    def enabled(self) -> bool:
        return bool(self.config and self.config.mode == "shinchan_tw_s1")

    def should_apply(
        self,
        user_text: str,
        *,
        coding_enabled: bool = False,
        system_turn: bool = False,
    ) -> bool:
        """Return True when persona should influence this turn."""
        if not self.enabled or not self.config:
            return False
        if self.config.apply_to == "off":
            return False
        if coding_enabled:
            return False
        if system_turn:
            return self.config.apply_to == "all"
        if self.config.apply_to == "all":
            return True
        return self.classify_scene(user_text) == self._SCENE_CHAT

    def classify_scene(self, text: str) -> str:
        if self._contains_any(text, self._HIGH_RISK_KEYWORDS):
            return self._SCENE_HIGH_RISK
        if self._contains_any(text, self._TASK_KEYWORDS):
            return self._SCENE_TASK
        return self._SCENE_CHAT

    def recommended_temperature(self, user_text: str, base_temperature: float) -> float:
        if not self.enabled or not self.config:
            return base_temperature

        scene = self.classify_scene(user_text)
        if self.config.intensity == "high":
            table = {
                self._SCENE_CHAT: 0.95,
                self._SCENE_TASK: 0.80,
                self._SCENE_HIGH_RISK: 0.45,
            }
        elif self.config.intensity == "medium":
            table = {
                self._SCENE_CHAT: 0.70,
                self._SCENE_TASK: 0.60,
                self._SCENE_HIGH_RISK: 0.35,
            }
        else:
            table = {
                self._SCENE_CHAT: 0.85,
                self._SCENE_TASK: 0.55,
                self._SCENE_HIGH_RISK: 0.25,
            }

        target = table.get(scene, base_temperature)
        return max(0.0, min(1.0, target))

    def build_runtime_hints(self, user_text: str) -> str | None:
        if not self.enabled or not self.config:
            return None

        scene = self.classify_scene(user_text)
        cues = self._retrieve_cues(user_text) if self.config.quote_retrieval else []
        scene_zh = {
            self._SCENE_CHAT: "闲聊",
            self._SCENE_TASK: "任务",
            self._SCENE_HIGH_RISK: "高风险",
        }[scene]
        strength = self._resolve_strength(scene)
        script_line = (
            "文字要求：最终输出必须全部使用简体中文；允许保留台味语气词（欸欸、好嘛、这样喔）。"
            if self.config.script == "simplified"
            else "文字要求：最终输出使用繁体中文。"
        )

        lines = [
            "当前人格模式：台版《蜡笔小新》S1语感。",
            "说话方式：短句、机灵、先接梗再给有效信息。",
            f"当前场景：{scene_zh}；风格强度：{strength}。",
            script_line,
            "禁止出现“作为AI/语言模型”等自我声明。",
        ]

        if scene == self._SCENE_HIGH_RISK:
            lines.append("当前话题偏高风险：降低玩梗密度，优先准确、边界和可执行建议。")
        elif scene == self._SCENE_TASK:
            lines.append("当前是任务场景：先给结论，再给最多3步操作。")

        if cues:
            lines.append("台版语感参考（检索增强，非固定台词）：")
            lines.extend(f"- {cue}" for cue in cues)
        special = self._special_rules(user_text)
        if special:
            lines.append("特殊约束：")
            lines.extend(f"- {rule}" for rule in special)

        return "\n".join(lines)

    async def normalize_output(
        self,
        text: str,
        provider: LLMProvider,
        model: str,
        max_tokens: int,
        reasoning_effort: str | None = None,
    ) -> str:
        """
        Normalize script requirements for persona output.

        Only active for shinchan mode + simplified script.
        """
        if not text or not self.enabled or not self.config:
            return text
        if self.config.script != "simplified":
            return text

        local = self.to_simplified(text)
        if self.traditional_ratio(local) <= 0.08:
            return local

        rewrite_messages = [
            {
                "role": "system",
                "content": (
                    "你是中文文本规范化助手。"
                    "把用户文本转换成简体中文，必须保留原语气、口头禅、换行和标点，"
                    "不得改变语义，不得补充内容。"
                    "只输出转换后的文本。"
                ),
            },
            {"role": "user", "content": local},
        ]
        try:
            response = await provider.chat(
                messages=rewrite_messages,
                tools=None,
                model=model,
                max_tokens=max(256, min(max_tokens, 2048)),
                temperature=0.2,
                reasoning_effort=reasoning_effort,
            )
        except Exception:
            return local

        rewritten = (response.content or "").strip()
        if not rewritten:
            return local
        return self.to_simplified(rewritten)

    @classmethod
    def to_simplified(cls, text: str) -> str:
        """Best-effort local Traditional -> Simplified conversion."""
        return "".join(cls._TRAD_TO_SIMPLIFIED_MAP.get(ch, ch) for ch in text)

    @classmethod
    def traditional_ratio(cls, text: str) -> float:
        """Estimate traditional-character ratio in a text."""
        cjk = [ch for ch in text if "\u4e00" <= ch <= "\u9fff"]
        if not cjk:
            return 0.0
        trad_count = sum(1 for ch in cjk if ch in cls._TRAD_HINT_CHARS)
        return trad_count / len(cjk)

    def _resolve_strength(self, scene: str) -> str:
        if not self.config:
            return "中"
        if self.config.intensity == "high":
            return "高"
        if self.config.intensity == "medium":
            return "中"
        if scene == self._SCENE_HIGH_RISK:
            return "低"
        if scene == self._SCENE_TASK:
            return "中"
        return "高"

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"[^\w\u4e00-\u9fff]+", "", text.lower())

    @staticmethod
    def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
        lowered = text.lower()
        return any(k in lowered for k in keywords)

    def _retrieve_cues(self, user_text: str, limit: int = 3) -> list[str]:
        if not self._quote_entries:
            return []
        normalized = self._normalize_text(user_text)
        scored: list[tuple[int, str]] = []

        for entry in self._quote_entries:
            patterns = entry.get("patterns", [])
            cue = str(entry.get("cue", "")).strip()
            if not cue:
                continue

            score = 0
            for p in patterns:
                raw = str(p).strip()
                if not raw:
                    continue
                raw_norm = self._normalize_text(raw)
                if raw in user_text or (raw_norm and raw_norm in normalized):
                    score += max(1, len(raw_norm))
            if score > 0:
                scored.append((score, cue))

        scored.sort(key=lambda x: x[0], reverse=True)
        uniq: list[str] = []
        for _, cue in scored:
            if cue not in uniq:
                uniq.append(cue)
            if len(uniq) >= limit:
                break
        return uniq

    def _load_quote_entries(self) -> list[dict[str, Any]]:
        path = Path(__file__).resolve().parent / "data" / "shinchan_tw_s1_quotes.json"
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

        entries = raw.get("entries") if isinstance(raw, dict) else raw
        if not isinstance(entries, list):
            return []
        return [e for e in entries if isinstance(e, dict)]

    def _special_rules(self, user_text: str) -> list[str]:
        """High-priority style corrections for known lines."""
        normalized = self._normalize_text(user_text)
        rules: list[str] = []
        if "你赖东东不错哦" in user_text or "赖东东不错" in user_text or "你賴東東不錯哦" in user_text:
            rules.append("把这句视为调侃梗，不要当成普通夸奖。")
            rules.append("禁止使用“谢谢/感谢/信任”这类正经感谢句。")
            rules.append("优先用欠揍又可爱的回嘴，短句收尾。")
        elif "赖东东不错" in normalized:
            rules.append("命中“赖东东不错”梗时，避免正经道谢。")
        return rules

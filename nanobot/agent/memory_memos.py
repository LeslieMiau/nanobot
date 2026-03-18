"""MemOS-backed memory store adapter for nanobot."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.config.schema import MemoryConfig


class MemOSStore:
    """
    Adapter wrapping MemOS NaiveTextMemory as a searchable fact store.

    Storage: workspace/memory/memos/textual_memory.json
    Backend: naive_text (keyword overlap, no external services required)

    This adapter bypasses MemOS's LLM-based extraction — nanobot already
    extracts structured facts via its own save_memory tool.  We ingest the
    already-extracted MEMORY.md lines directly and use MemOS only for
    keyword-overlap search at context-build time.
    """

    def __init__(self, workspace: Path, config: MemoryConfig) -> None:
        from memos.configs.llm import LLMConfigFactory
        from memos.configs.memory import NaiveTextMemoryConfig
        from memos.memories.textual.naive import NaiveTextMemory

        self._mem_dir = workspace / "memory" / "memos"
        self._mem_dir.mkdir(parents=True, exist_ok=True)
        self._top_k = config.memos_top_k

        llm_cfg: dict = {"model_name_or_path": config.memos_llm_model}
        if config.memos_llm_api_base:
            llm_cfg["api_base"] = config.memos_llm_api_base
        if config.memos_llm_api_key:
            llm_cfg["api_key"] = config.memos_llm_api_key

        extractor_llm = LLMConfigFactory(backend=config.memos_llm_backend, config=llm_cfg)
        mem_config = NaiveTextMemoryConfig(extractor_llm=extractor_llm)
        self._memory = NaiveTextMemory(mem_config)

        # Restore previously persisted facts (no-op on first run)
        try:
            self._memory.load(str(self._mem_dir))
            logger.debug("MemOSStore: loaded {} facts from {}", len(self._memory.memories), self._mem_dir)
        except Exception:
            logger.debug("MemOSStore: starting with empty fact store")

    def search(self, query: str) -> list[str]:
        """Return up to top_k fact strings relevant to the query (keyword overlap)."""
        try:
            results = self._memory.search(query=query, top_k=self._top_k)
            return [r.memory for r in results if r.memory]
        except Exception:
            logger.warning("MemOSStore.search failed")
            return []

    def upsert_facts(self, memory_md_content: str) -> None:
        """Sync new/changed facts from MEMORY.md content into the MemOS fact store.

        Only lines that are not already in the store are added (no duplicate insertion).
        Markdown headings (lines starting with #) are skipped.
        """
        from memos.memories.textual.item import TextualMemoryItem

        try:
            lines = [
                line.strip()
                for line in memory_md_content.splitlines()
                if line.strip() and not line.startswith("#")
            ]
            existing_texts = {m["memory"] for m in self._memory.memories}
            new_items = [
                TextualMemoryItem(memory=line, metadata={"source": "file"})
                for line in lines
                if line not in existing_texts
            ]
            if new_items:
                self._memory.add(new_items)
                self._memory.dump(str(self._mem_dir))
                logger.debug("MemOSStore: added {} new facts", len(new_items))
        except Exception:
            logger.warning("MemOSStore.upsert_facts failed")

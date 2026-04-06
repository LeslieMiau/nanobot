from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "verify_homepod_e2e.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_homepod_e2e", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_action_count_handles_numeric_and_missing_values() -> None:
    module = _load_module()

    assert module.parse_action_count("4") == 4
    assert module.parse_action_count("action count:5") == 5
    assert module.parse_action_count("missing value") is None


def test_filter_relevant_lines_respects_speaker_filter() -> None:
    module = _load_module()
    sample = """
2026-04-05 11:30:21.683 | INFO | nanobot.api.server:handle_voice_ask:232 - Voice ask speaker=homepod text=你好
2026-04-05 11:30:23.966 | INFO | nanobot.agent.loop:_process_message:657 - Response to api:user: 你好。
2026-04-05 11:31:21.683 | INFO | nanobot.api.server:handle_voice_ask:232 - Voice ask speaker=e2e-api-check text=你好
""".strip()

    assert len(module.filter_relevant_lines(sample)) == 3
    filtered = module.filter_relevant_lines(sample, "homepod")
    assert filtered == [
        "2026-04-05 11:30:21.683 | INFO | nanobot.api.server:handle_voice_ask:232 - Voice ask speaker=homepod text=你好",
        "2026-04-05 11:30:23.966 | INFO | nanobot.agent.loop:_process_message:657 - Response to api:user: 你好。",
    ]

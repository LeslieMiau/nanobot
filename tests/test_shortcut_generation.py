"""Regression coverage for Siri Shortcut artifacts and documentation links."""

from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_shortcut.py"
README_PATH = REPO_ROOT / "README.md"
HOMEPOD_SETUP_PATH = REPO_ROOT / "docs" / "HOMEPOD_SETUP.md"


def _load_shortcut_module():
    spec = importlib.util.spec_from_file_location("generate_shortcut", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_recommended_shortcuts_keep_expected_names_and_api_shape() -> None:
    module = _load_shortcut_module()

    test_name, test_shortcut = module.build_test_shortcut()
    interactive_name, interactive_shortcut = module.build_interactive_shortcut()

    assert test_name == "测试助手"
    assert test_shortcut["WFWorkflowName"] == "测试助手"
    assert interactive_name == "纳博特"
    assert interactive_shortcut["WFWorkflowName"] == "纳博特"

    test_download = test_shortcut["WFWorkflowActions"][0]["WFWorkflowActionParameters"]
    assert test_download["WFHTTPMethod"] == "POST"
    assert test_download["WFHTTPBodyType"] == "JSON"
    assert test_download["WFURL"].endswith("/chat")

    test_header_items = test_download["WFHTTPHeaders"]["Value"]["WFDictionaryFieldValueItems"]
    test_headers = {
        item["WFKey"]["Value"]["string"]: item["WFValue"]["Value"]["string"]
        for item in test_header_items
    }
    assert test_headers["Content-Type"] == "application/json"
    assert test_headers["Authorization"].startswith("Bearer ")

    test_json_items = test_download["WFJSONValues"]["Value"]["WFDictionaryFieldValueItems"]
    test_json = {
        item["WFKey"]["Value"]["string"]: item["WFValue"]["Value"]["string"]
        for item in test_json_items
    }
    assert test_json == {"text": "你好", "speaker": "homepod"}

    interactive_actions = interactive_shortcut["WFWorkflowActions"]
    interactive_ids = [
        action["WFWorkflowActionIdentifier"]
        for action in interactive_actions
    ]
    assert interactive_ids[:4] == [
        "is.workflow.actions.date",
        "is.workflow.actions.format.date",
        "is.workflow.actions.repeat.count",
        "is.workflow.actions.dictatetext",
    ]
    assert interactive_ids.count("is.workflow.actions.repeat.count") == 2
    assert "is.workflow.actions.showresult" not in interactive_ids
    assert "is.workflow.actions.exit" in interactive_ids
    assert interactive_ids.count("is.workflow.actions.conditional") == 10

    interactive_download = next(
        action["WFWorkflowActionParameters"]
        for action in interactive_actions
        if action["WFWorkflowActionIdentifier"] == "is.workflow.actions.downloadurl"
    )
    assert interactive_download["WFHTTPMethod"] == "POST"
    assert interactive_download["WFHTTPBodyType"] == "JSON"
    assert interactive_download["WFURL"].endswith("/chat")

    header_items = interactive_download["WFHTTPHeaders"]["Value"]["WFDictionaryFieldValueItems"]
    headers = {
        item["WFKey"]["Value"]["string"]: item["WFValue"]["Value"]["string"]
        for item in header_items
    }
    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"].startswith("Bearer ")

    json_items = interactive_download["WFJSONValues"]["Value"]["WFDictionaryFieldValueItems"]
    keys = [item["WFKey"]["Value"]["string"] for item in json_items]
    assert keys == ["text", "speaker", "session_id"]

    text_item, speaker_item, session_item = json_items
    assert speaker_item["WFValue"]["Value"]["string"] == "homepod"
    assert text_item["WFValue"]["Value"]["attachmentsByRange"]["0,1"]["Value"]["OutputName"] == "问题"
    assert (
        session_item["WFValue"]["Value"]["attachmentsByRange"]["0,1"]["Value"]["OutputName"]
        == "session_id"
    )

    dictionary_keys = [
        action["WFWorkflowActionParameters"]["WFDictionaryKey"]
        for action in interactive_actions
        if action["WFWorkflowActionIdentifier"] == "is.workflow.actions.getvalueforkey"
    ]
    assert dictionary_keys == ["reply", "end_conversation"]

    start_conditions = [
        action["WFWorkflowActionParameters"]
        for action in interactive_actions
        if action["WFWorkflowActionIdentifier"] == "is.workflow.actions.conditional"
        and action["WFWorkflowActionParameters"].get("WFControlFlowMode") == 0
    ]
    assert any(condition["WFCondition"] == 101 for condition in start_conditions)
    assert sum(condition["WFCondition"] == 99 for condition in start_conditions) == len(module.LOCAL_EXIT_PHRASES)
    assert any(
        condition["WFCondition"] == 4
        and condition.get("WFConditionalActionString") == "1"
        for condition in start_conditions
    )

    assert test_shortcut["WFWorkflowActions"][2]["WFWorkflowActionIdentifier"] == "is.workflow.actions.showresult"
    assert test_shortcut["WFWorkflowActions"][3]["WFWorkflowActionIdentifier"] == "is.workflow.actions.speaktext"
    assert "is.workflow.actions.speaktext" in interactive_ids


def test_docs_expose_recommended_shortcut_links() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    setup_doc = HOMEPOD_SETUP_PATH.read_text(encoding="utf-8")

    assert "./docs/HOMEPOD_SETUP.md" in readme
    assert "./测试助手.shortcut" in readme
    assert "./纳博特.shortcut" in readme

    assert "../测试助手.shortcut" in setup_doc
    assert "../纳博特.shortcut" in setup_doc
    assert "嘿 Siri, 运行纳博特" in setup_doc
    assert "唤起一次后连续聊" in setup_doc
    assert "一句话直达" in setup_doc
    assert "session_id" in setup_doc
    assert "POST /chat" in setup_doc
    assert "ClawPod-compatible `POST /chat` bridge" in readme

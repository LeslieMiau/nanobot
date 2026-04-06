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

    assert interactive_shortcut["WFWorkflowActions"][0]["WFWorkflowActionIdentifier"] == "is.workflow.actions.dictatetext"

    interactive_download = interactive_shortcut["WFWorkflowActions"][1]["WFWorkflowActionParameters"]
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
    assert keys == ["text", "speaker"]
    assert interactive_shortcut["WFWorkflowActions"][2]["WFWorkflowActionParameters"]["WFDictionaryKey"] == "reply"
    assert test_shortcut["WFWorkflowActions"][2]["WFWorkflowActionIdentifier"] == "is.workflow.actions.showresult"
    assert interactive_shortcut["WFWorkflowActions"][3]["WFWorkflowActionIdentifier"] == "is.workflow.actions.showresult"
    assert test_shortcut["WFWorkflowActions"][3]["WFWorkflowActionIdentifier"] == "is.workflow.actions.speaktext"
    assert interactive_shortcut["WFWorkflowActions"][4]["WFWorkflowActionIdentifier"] == "is.workflow.actions.speaktext"


def test_docs_expose_recommended_shortcut_links() -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    setup_doc = HOMEPOD_SETUP_PATH.read_text(encoding="utf-8")

    assert "./docs/HOMEPOD_SETUP.md" in readme
    assert "./测试助手.shortcut" in readme
    assert "./纳博特.shortcut" in readme

    assert "../测试助手.shortcut" in setup_doc
    assert "../纳博特.shortcut" in setup_doc
    assert "嘿 Siri, 运行纳博特" in setup_doc
    assert "弹出 reply 文本并朗读" in setup_doc
    assert "POST /chat" in setup_doc
    assert "ClawPod-compatible `POST /chat` bridge" in readme

#!/usr/bin/env python3
"""生成 Apple Shortcut (.shortcut) 文件。

最简方案: 用纯文本 URL + 单次 GET 请求，不依赖变量引用。
缺点: 问题文本硬编码为 "hello"，用户需要在 Shortcuts App 里手动改。

实际方案: 生成两个版本 —
  1. 固定问题版（验证 API 连通性）
  2. 交互版（按 Apple 官方 Web API 模式使用 POST JSON）
"""

import plistlib
import uuid
from pathlib import Path

# ============================================================
NANOBOT_HOST = "192.168.3.79"
NANOBOT_PORT = 8900
API_KEY = "nb-3b7d4b91132c9bb850c2646f92860dc8"
SPEAKER = "homepod"
# ============================================================

ENDPOINT = f"http://{NANOBOT_HOST}:{NANOBOT_PORT}/v1/voice/ask"


def _uuid():
    return str(uuid.uuid4()).upper()


def _ref(uid, name):
    return {
        "Value": {"OutputUUID": uid, "OutputName": name, "Type": "ActionOutput"},
        "WFSerializationType": "WFTextTokenAttachment",
    }


def _text(attachments, s):
    return {
        "Value": {"attachmentsByRange": attachments, "string": s},
        "WFSerializationType": "WFTextTokenString",
    }


def _simple_text(s):
    """纯文本，无变量。"""
    return {"Value": {"string": s}, "WFSerializationType": "WFTextTokenString"}


def build_test_shortcut():
    """固定问题版 — 验证 API 连通性。"""
    url_id = _uuid()
    dict_id = _uuid()

    test_url = f"{ENDPOINT}?text=%E4%BD%A0%E5%A5%BD&speaker={SPEAKER}&key={API_KEY}"

    return "测试助手", {
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {
            "WFWorkflowIconStartColor": 463140863,
            "WFWorkflowIconGlyphNumber": 59750,
        },
        "WFWorkflowClientVersion": "2802.0.2",
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowHasOutputFallback": False,
        "WFWorkflowActions": [
            # 1. 获取 URL — 纯字符串，零变量
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
                "WFWorkflowActionParameters": {
                    "WFURL": test_url,
                    "WFHTTPMethod": "GET",
                    "UUID": url_id,
                    "CustomOutputName": "回复",
                },
            },
            # 2. 取字典值
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
                "WFWorkflowActionParameters": {
                    "WFInput": _ref(url_id, "回复"),
                    "WFDictionaryKey": "reply",
                    "UUID": dict_id,
                    "CustomOutputName": "回答",
                },
            },
            # 3. 朗读
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.speaktext",
                "WFWorkflowActionParameters": {
                    "WFText": _text({"0,1": _ref(dict_id, "回答")}, "\uFFFC"),
                    "WFSpeakTextWait": True,
                },
            },
        ],
        "WFWorkflowInputContentItemClasses": ["WFStringContentItem"],
        "WFWorkflowTypes": [],
        "WFWorkflowHasShortcutInputVariables": False,
        "WFQuickActionSurfaces": [],
        "WFWorkflowName": "测试助手",
    }


def build_interactive_shortcut():
    """交互版 — Ask for Input + POST JSON + 朗读 reply。"""
    ask_id = _uuid()
    url_id = _uuid()
    dict_id = _uuid()

    return "问机器人", {
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {
            "WFWorkflowIconStartColor": 463140863,
            "WFWorkflowIconGlyphNumber": 59750,
        },
        "WFWorkflowClientVersion": "2802.0.2",
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowHasOutputFallback": False,
        "WFWorkflowActions": [
            # 1. 要求输入
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.ask",
                "WFWorkflowActionParameters": {
                    "WFAskActionPrompt": "你想问什么？",
                    "WFInputType": "Text",
                    "UUID": ask_id,
                    "CustomOutputName": "问题",
                },
            },
            # 2. 获取 URL 内容（Apple 官方 Web API 模式：POST + JSON body）
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
                "WFWorkflowActionParameters": {
                    "WFURL": ENDPOINT,
                    "WFHTTPMethod": "POST",
                    "WFHTTPBodyType": "JSON",
                    "WFHTTPHeaders": {
                        "Value": {
                            "WFDictionaryFieldValueItems": [
                                {
                                    "WFItemType": 0,
                                    "WFKey": _simple_text("Content-Type"),
                                    "WFValue": _simple_text("application/json"),
                                },
                                {
                                    "WFItemType": 0,
                                    "WFKey": _simple_text("Authorization"),
                                    "WFValue": _simple_text(f"Bearer {API_KEY}"),
                                },
                            ]
                        },
                        "WFSerializationType": "WFDictionaryFieldValue",
                    },
                    "WFJSONValues": {
                        "Value": {
                            "WFDictionaryFieldValueItems": [
                                {
                                    "WFItemType": 0,
                                    "WFKey": _simple_text("text"),
                                    "WFValue": _text({"0,1": _ref(ask_id, "问题")}, "\uFFFC"),
                                },
                                {
                                    "WFItemType": 0,
                                    "WFKey": _simple_text("speaker"),
                                    "WFValue": _simple_text(SPEAKER),
                                },
                            ]
                        },
                        "WFSerializationType": "WFDictionaryFieldValue",
                    },
                    "UUID": url_id,
                    "CustomOutputName": "回复",
                },
            },
            # 3. 取字典值
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
                "WFWorkflowActionParameters": {
                    "WFInput": _ref(url_id, "回复"),
                    "WFDictionaryKey": "reply",
                    "UUID": dict_id,
                    "CustomOutputName": "回答",
                },
            },
            # 4. 朗读
            {
                "WFWorkflowActionIdentifier": "is.workflow.actions.speaktext",
                "WFWorkflowActionParameters": {
                    "WFText": _text({"0,1": _ref(dict_id, "回答")}, "\uFFFC"),
                    "WFSpeakTextWait": True,
                },
            },
        ],
        "WFWorkflowInputContentItemClasses": ["WFStringContentItem"],
        "WFWorkflowTypes": [],
        "WFWorkflowHasShortcutInputVariables": False,
        "WFQuickActionSurfaces": [],
        "WFWorkflowName": "问机器人",
    }


def main():
    out_dir = Path(__file__).resolve().parent.parent

    for name, data in [build_test_shortcut(), build_interactive_shortcut()]:
        out = out_dir / f"{name}.shortcut"
        with open(out, "wb") as f:
            plistlib.dump(data, f, fmt=plistlib.FMT_BINARY)
        print(f"已生成: {out}")

    print()
    print("第一步: 导入并运行「测试助手」验证 API 连通性")
    print("第二步: 导入「问机器人」作为 Siri 日常入口")
    print('使用: "嘿 Siri, 运行问机器人"')


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""生成 Apple Shortcut (.shortcut) 文件，可直接 AirDrop 到 iPhone 导入。

用法:
    python3 scripts/generate_shortcut.py

生成后双击 .shortcut 文件（macOS）或 AirDrop 到 iPhone 即可导入。
"""

import plistlib
import uuid
import sys
from pathlib import Path

# ============================================================
# 配置 — 按需修改
# ============================================================
NANOBOT_HOST = "192.168.3.79"
NANOBOT_PORT = 8900
API_KEY = "nb-3b7d4b91132c9bb850c2646f92860dc8"
SESSION_ID = "homepod"
SHORTCUT_NAME = "Ask Nanobot"
# ============================================================

ENDPOINT = f"http://{NANOBOT_HOST}:{NANOBOT_PORT}/v1/voice/ask"


def _uuid():
    return str(uuid.uuid4()).upper()


def _var_ref(output_uuid, output_name, agg_type=None):
    """构造对前一个动作输出的变量引用（Magic Variable）。"""
    ref = {
        "Value": {
            "OutputUUID": output_uuid,
            "OutputName": output_name,
            "Type": "ActionOutput",
        },
        "WFSerializationType": "WFTextTokenAttachment",
    }
    if agg_type is not None:
        ref["Value"]["Aggrandizements"] = agg_type
    return ref


def _text_token(attachments_by_range, string):
    """构造带有变量占位的富文本。"""
    return {
        "Value": {
            "attachmentsByRange": attachments_by_range,
            "string": string,
        },
        "WFSerializationType": "WFTextTokenString",
    }


def build_shortcut():
    # 每个动作的输出 UUID
    dictate_uuid = _uuid()
    url_uuid = _uuid()
    dict_uuid = _uuid()

    actions = []

    # ── 1. 听写文本 ──
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.dictatetext",
        "WFWorkflowActionParameters": {
            "WFDictateTextStopListening": "After Pause",  # 说完自动停
            "UUID": dictate_uuid,
            "CustomOutputName": "听写文本",
        },
    })

    # ── 2. 获取 URL 内容 (POST /v1/voice/ask) ──
    # 构造 JSON body: {"text": <dictated>, "session_id": "homepod"}
    body_text_field = _text_token(
        {"\uFFFC": _var_ref(dictate_uuid, "听写文本")},
        "\uFFFC",  # placeholder for the variable
    )

    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
        "WFWorkflowActionParameters": {
            "WFURL": ENDPOINT,
            "WFHTTPMethod": "POST",
            "WFHTTPHeaders": {
                "Value": {
                    "WFDictionaryFieldValueItems": [
                        {
                            "WFItemType": 0,
                            "WFKey": {
                                "Value": {"string": "Content-Type"},
                                "WFSerializationType": "WFTextTokenString",
                            },
                            "WFValue": {
                                "Value": {"string": "application/json"},
                                "WFSerializationType": "WFTextTokenString",
                            },
                        },
                        {
                            "WFItemType": 0,
                            "WFKey": {
                                "Value": {"string": "Authorization"},
                                "WFSerializationType": "WFTextTokenString",
                            },
                            "WFValue": {
                                "Value": {"string": f"Bearer {API_KEY}"},
                                "WFSerializationType": "WFTextTokenString",
                            },
                        },
                    ],
                },
                "WFSerializationType": "WFDictionaryFieldValue",
            },
            "WFHTTPBodyType": "JSON",
            "WFJSONValues": {
                "Value": {
                    "WFDictionaryFieldValueItems": [
                        {
                            "WFItemType": 0,
                            "WFKey": {
                                "Value": {"string": "text"},
                                "WFSerializationType": "WFTextTokenString",
                            },
                            "WFValue": body_text_field,
                        },
                        {
                            "WFItemType": 0,
                            "WFKey": {
                                "Value": {"string": "session_id"},
                                "WFSerializationType": "WFTextTokenString",
                            },
                            "WFValue": {
                                "Value": {"string": SESSION_ID},
                                "WFSerializationType": "WFTextTokenString",
                            },
                        },
                    ],
                },
                "WFSerializationType": "WFDictionaryFieldValue",
            },
            "UUID": url_uuid,
            "CustomOutputName": "API 回复",
        },
    })

    # ── 3. 获取字典值 (key = "text") ──
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
        "WFWorkflowActionParameters": {
            "WFInput": _var_ref(url_uuid, "API 回复"),
            "WFDictionaryKey": "text",
            "UUID": dict_uuid,
            "CustomOutputName": "回答文本",
        },
    })

    # ── 4. 朗读文本 ──
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.speaktext",
        "WFWorkflowActionParameters": {
            "WFInput": _var_ref(dict_uuid, "回答文本"),  # 引用上一步输出，保持兼容
            "WFText": _text_token(
                {"\uFFFC": _var_ref(dict_uuid, "回答文本")},
                "\uFFFC",
            ),
        },
    })

    shortcut = {
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {
            "WFWorkflowIconStartColor": 463140863,  # 蓝紫色
            "WFWorkflowIconGlyphNumber": 59750,  # 麦克风图标
        },
        "WFWorkflowClientVersion": "2802.0.2",
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowHasOutputFallback": False,
        "WFWorkflowActions": actions,
        "WFWorkflowInputContentItemClasses": [
            "WFStringContentItem",
        ],
        "WFWorkflowTypes": [],
        "WFWorkflowHasShortcutInputVariables": False,
        "WFQuickActionSurfaces": [],
        "WFWorkflowName": SHORTCUT_NAME,
    }

    return shortcut


def main():
    shortcut = build_shortcut()

    out_dir = Path(__file__).resolve().parent.parent
    out_path = out_dir / f"{SHORTCUT_NAME.replace(' ', '_')}.shortcut"

    with open(out_path, "wb") as f:
        plistlib.dump(shortcut, f, fmt=plistlib.FMT_BINARY)

    print(f"✅ 已生成: {out_path}")
    print()
    print("导入方式:")
    print(f"  • macOS: 双击 {out_path.name} 即可导入到快捷指令")
    print(f"  • iPhone: AirDrop 发送 {out_path.name} 到手机")
    print()
    print("使用方式:")
    print(f'  对 HomePod 说: "嘿 Siri, {SHORTCUT_NAME}"')
    print()
    print("配置信息:")
    print(f"  API 地址: {ENDPOINT}")
    print(f"  API Key:  {API_KEY[:20]}...")
    print(f"  Session:  {SESSION_ID}")


if __name__ == "__main__":
    main()

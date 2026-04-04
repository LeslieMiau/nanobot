#!/usr/bin/env python3
"""生成 Apple Shortcut (.shortcut) 文件。

只用 3 个动作，避免复杂的变量引用：
  1. 要求输入 → 得到问题
  2. URL (把问题拼进 URL 参数) → 得到 JSON
  3. 朗读 → 读出 reply 字段
"""

import plistlib
import uuid
from pathlib import Path
from urllib.parse import quote

# ============================================================
# 配置
# ============================================================
NANOBOT_HOST = "192.168.3.79"
NANOBOT_PORT = 8900
API_KEY = "nb-3b7d4b91132c9bb850c2646f92860dc8"
SPEAKER = "homepod"
SHORTCUT_NAME = "问机器人"
# ============================================================


def _uuid():
    return str(uuid.uuid4()).upper()


def _action_output(uid, name):
    return {
        "Value": {
            "OutputUUID": uid,
            "OutputName": name,
            "Type": "ActionOutput",
        },
        "WFSerializationType": "WFTextTokenAttachment",
    }


def _text(attachments, string):
    return {
        "Value": {
            "attachmentsByRange": attachments,
            "string": string,
        },
        "WFSerializationType": "WFTextTokenString",
    }


def build():
    ask_id = _uuid()
    url_id = _uuid()
    text_id = _uuid()
    dict_id = _uuid()

    base = f"http://{NANOBOT_HOST}:{NANOBOT_PORT}/v1/voice/ask?speaker={SPEAKER}&key={API_KEY}&text="

    actions = []

    # 1. 要求输入
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.ask",
        "WFWorkflowActionParameters": {
            "WFAskActionPrompt": "你想问什么？",
            "WFInputType": "Text",
            "UUID": ask_id,
            "CustomOutputName": "问题",
        },
    })

    # 2. 文本：拼接完整 URL = base + 用户输入
    #    用 Text 动作把固定前缀和变量拼在一起
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.gettext",
        "WFWorkflowActionParameters": {
            "WFTextActionText": _text(
                # \uFFFC 是占位符，表示此处插入变量
                {f"{len(base)},1": _action_output(ask_id, "问题")},
                base + "\uFFFC",
            ),
            "UUID": text_id,
            "CustomOutputName": "请求地址",
        },
    })

    # 3. 获取 URL 内容 (GET 请求，无需 JSON body)
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.downloadurl",
        "WFWorkflowActionParameters": {
            "WFHTTPMethod": "GET",
            "WFURL": _text(
                {"\uFFFC": _action_output(text_id, "请求地址")},
                "\uFFFC",
            ),
            "WFHTTPHeaders": {
                "Value": {
                    "WFDictionaryFieldValueItems": [
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
            "UUID": url_id,
            "CustomOutputName": "回复",
        },
    })

    # 4. 取字典 reply 字段
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.getvalueforkey",
        "WFWorkflowActionParameters": {
            "WFInput": _action_output(url_id, "回复"),
            "WFDictionaryKey": "reply",
            "UUID": dict_id,
            "CustomOutputName": "回答",
        },
    })

    # 5. 朗读
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.speaktext",
        "WFWorkflowActionParameters": {
            "WFText": _text(
                {"\uFFFC": _action_output(dict_id, "回答")},
                "\uFFFC",
            ),
            "WFSpeakTextWait": True,
        },
    })

    return {
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {
            "WFWorkflowIconStartColor": 463140863,
            "WFWorkflowIconGlyphNumber": 59750,
        },
        "WFWorkflowClientVersion": "2802.0.2",
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowHasOutputFallback": False,
        "WFWorkflowActions": actions,
        "WFWorkflowInputContentItemClasses": ["WFStringContentItem"],
        "WFWorkflowTypes": [],
        "WFWorkflowHasShortcutInputVariables": False,
        "WFQuickActionSurfaces": [],
        "WFWorkflowName": SHORTCUT_NAME,
    }


def main():
    out_dir = Path(__file__).resolve().parent.parent
    out_path = out_dir / f"{SHORTCUT_NAME}.shortcut"

    with open(out_path, "wb") as f:
        plistlib.dump(build(), f, fmt=plistlib.FMT_BINARY)

    print(f"已生成: {out_path}")
    print(f"使用: \"嘿 Siri, 运行{SHORTCUT_NAME}\"")


if __name__ == "__main__":
    main()

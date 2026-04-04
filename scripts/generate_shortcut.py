#!/usr/bin/env python3
"""生成 Apple Shortcut (.shortcut) 文件。

流程: 「要求输入」→ 运行 Shell 脚本 (curl) → 朗读结果
"""

import plistlib
import uuid
from pathlib import Path

# ============================================================
# 配置 — 按需修改
# ============================================================
NANOBOT_HOST = "192.168.3.79"
NANOBOT_PORT = 8900
API_KEY = "nb-3b7d4b91132c9bb850c2646f92860dc8"
SESSION_ID = "homepod"
SHORTCUT_NAME = "问机器人"
# ============================================================

ENDPOINT = f"http://{NANOBOT_HOST}:{NANOBOT_PORT}/v1/voice/ask"


def _uuid():
    return str(uuid.uuid4()).upper()


def _var_ref(output_uuid, output_name):
    return {
        "Value": {
            "OutputUUID": output_uuid,
            "OutputName": output_name,
            "Type": "ActionOutput",
        },
        "WFSerializationType": "WFTextTokenAttachment",
    }


def _text_token(attachments_by_range, string):
    return {
        "Value": {
            "attachmentsByRange": attachments_by_range,
            "string": string,
        },
        "WFSerializationType": "WFTextTokenString",
    }


def build_shortcut():
    ask_uuid = _uuid()
    shell_uuid = _uuid()

    actions = []

    # ── 1. 要求输入 ──
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.ask",
        "WFWorkflowActionParameters": {
            "WFAskActionPrompt": "你想问什么？",
            "WFInputType": "Text",
            "UUID": ask_uuid,
            "CustomOutputName": "用户提问",
        },
    })

    # ── 2. 运行 Shell 脚本 ──
    # 用 curl 调用 API，用 python3 解析 JSON 提取 text 字段
    shell_script = f'''QUESTION=$(cat)
ESCAPED=$(printf '%s' "$QUESTION" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
RESP=$(curl -s -m 120 -X POST "{ENDPOINT}" \\
  -H "Content-Type: application/json" \\
  -H "Authorization: Bearer {API_KEY}" \\
  -d "{{\\"text\\": ${{ESCAPED}}, \\"session_id\\": \\"{SESSION_ID}\\"}}")
echo "$RESP" | python3 -c 'import json,sys; print(json.loads(sys.stdin.read()).get("text","抱歉，没有获得回复"))'
'''

    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.runscript",
        "WFWorkflowActionParameters": {
            "WFShellScript": shell_script,
            "WFShellScriptInputType": "Text",  # 传入上一步输出作为 stdin
            "WFInput": _text_token(
                {"\uFFFC": _var_ref(ask_uuid, "用户提问")},
                "\uFFFC",
            ),
            "Shell": "/bin/bash",
            "UUID": shell_uuid,
            "CustomOutputName": "回答",
        },
    })

    # ── 3. 朗读文本 ──
    actions.append({
        "WFWorkflowActionIdentifier": "is.workflow.actions.speaktext",
        "WFWorkflowActionParameters": {
            "WFText": _text_token(
                {"\uFFFC": _var_ref(shell_uuid, "回答")},
                "\uFFFC",
            ),
        },
    })

    shortcut = {
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
    out_path = out_dir / f"{SHORTCUT_NAME}.shortcut"

    with open(out_path, "wb") as f:
        plistlib.dump(shortcut, f, fmt=plistlib.FMT_BINARY)

    print(f"已生成: {out_path}")
    print()
    print("使用方式:")
    print(f'  "嘿 Siri, 运行{SHORTCUT_NAME}"')
    print(f"  API: {ENDPOINT}")


if __name__ == "__main__":
    main()

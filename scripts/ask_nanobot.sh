#!/bin/bash
# 问 Nanobot — 通过命令行或 Apple Shortcuts 的「运行 Shell 脚本」调用
#
# 用法:
#   ./ask_nanobot.sh "你好"
#   echo "你好" | ./ask_nanobot.sh

HOST="192.168.3.79"
PORT="8900"
API_KEY="nb-3b7d4b91132c9bb850c2646f92860dc8"
SESSION="homepod"

# 获取输入
if [ -n "$1" ]; then
    QUESTION="$1"
else
    read -r QUESTION
fi

[ -z "$QUESTION" ] && echo "请输入问题" && exit 1

# 转义 JSON
ESCAPED=$(printf '%s' "$QUESTION" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')

RESPONSE=$(curl -s -m 120 \
  -X POST "http://${HOST}:${PORT}/v1/voice/ask" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${API_KEY}" \
  -d "{\"text\": ${ESCAPED}, \"session_id\": \"${SESSION}\"}")

# 提取 reply 字段，兼容旧版 text 字段
TEXT=$(echo "$RESPONSE" | python3 -c 'import json,sys; data=json.loads(sys.stdin.read()); print(data.get("reply") or data.get("text","无回复"))')

echo "$TEXT"

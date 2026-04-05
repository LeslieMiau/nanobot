#!/usr/bin/env python3
"""HomePod + Siri shortcut E2E diagnostics.

Automates the locally testable stages:
  1. API process/listener + /health
  2. /v1/voice/ask business response
  3. macOS Shortcuts runtime + shortcut shape

It also provides a lightweight log watch mode for iPhone / Siri / HomePod
device-side checks so the same evidence model can be reused end to end.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


DEFAULT_HOST = "192.168.3.79"
DEFAULT_PORT = 8900
DEFAULT_API_KEY = "nb-3b7d4b91132c9bb850c2646f92860dc8"
DEFAULT_LOG_FILE = "/private/tmp/nanobot-api.log"
DEFAULT_TEST_SHORTCUT = "测试助手"
DEFAULT_INTERACTIVE_SHORTCUT = "纳博特"
DEFAULT_TEST_TEXT = "你好"


@dataclass
class CommandResult:
    code: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class StageResult:
    name: str
    passed: bool
    evidence: list[str]
    fix_hint: str


def run_command(argv: list[str], timeout: float = 20.0) -> CommandResult:
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return CommandResult(
            code=124,
            stdout=stdout.strip(),
            stderr=(stderr or f"timed out after {timeout:.1f}s").strip(),
            timed_out=True,
        )
    return CommandResult(
        code=completed.returncode,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )


def run_shell(command: str, timeout: float = 20.0) -> CommandResult:
    return run_command(["/bin/zsh", "-lc", command], timeout=timeout)


def snapshot_log(log_file: Path) -> int:
    if not log_file.exists():
        return 0
    return log_file.stat().st_size


def read_log_delta(log_file: Path, offset: int) -> str:
    if not log_file.exists():
        return ""
    with log_file.open("r", encoding="utf-8", errors="replace") as handle:
        handle.seek(offset)
        return handle.read()


def filter_relevant_lines(text: str, speaker: str | None = None) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        if "nanobot.api.server:handle_voice_ask" in raw:
            if speaker and f"speaker={speaker}" not in raw:
                continue
            lines.append(raw)
            continue
        if "nanobot.agent.loop:_process_message:657 - Response to api:user:" in raw:
            lines.append(raw)
    return lines


def parse_action_count(text: str) -> int | None:
    match = re.search(r"(\d+)", text)
    if not match:
        return None
    return int(match.group(1))


def shortcut_action_count(name: str) -> int | None:
    script = (
        'tell application "Shortcuts"\n'
        f'  try\n    return action count of first shortcut whose name is "{name}"\n'
        '  on error errMsg\n    return errMsg\n  end try\n'
        "end tell"
    )
    result = run_command(["osascript", "-e", script], timeout=15.0)
    if result.code != 0:
        return None
    return parse_action_count(result.stdout)


def format_stage(stage: StageResult) -> str:
    status = "PASS" if stage.passed else "FAIL"
    lines = [f"[{status}] {stage.name}"]
    lines.extend(f"  - {item}" for item in stage.evidence)
    if not stage.passed:
        lines.append(f"  - next fix: {stage.fix_hint}")
    return "\n".join(lines)


def stage_api_baseline(args: argparse.Namespace) -> StageResult:
    evidence: list[str] = []
    listener = run_shell(f"lsof -nP -iTCP:{args.port} -sTCP:LISTEN", timeout=10.0)
    listener_ok = listener.code == 0 and str(args.port) in listener.stdout
    evidence.append(
        f"listener {'ok' if listener_ok else 'missing'} on :{args.port}"
    )

    health = run_command(
        ["curl", "-sS", "-m", "5", f"http://{args.host}:{args.port}/health"],
        timeout=10.0,
    )
    health_ok = health.code == 0 and '"status": "ok"' in health.stdout
    evidence.append(f"/health -> {health.stdout or health.stderr or f'code={health.code}'}")

    marker = snapshot_log(args.log_file)
    payload = json.dumps({"text": args.api_text, "speaker": args.api_speaker}, ensure_ascii=False)
    voice = run_command(
        [
            "curl",
            "-sS",
            "-m",
            "15",
            "-X",
            "POST",
            f"http://{args.host}:{args.port}/v1/voice/ask",
            "-H",
            "Content-Type: application/json",
            "-H",
            f"Authorization: Bearer {args.api_key}",
            "-d",
            payload,
        ],
        timeout=20.0,
    )
    voice_ok = False
    if voice.code == 0:
        try:
            body = json.loads(voice.stdout)
            voice_ok = isinstance(body.get("reply"), str) and bool(body["reply"].strip())
            evidence.append(f"/v1/voice/ask reply -> {body.get('reply', '')[:80]}")
        except json.JSONDecodeError:
            evidence.append(f"/v1/voice/ask invalid json -> {voice.stdout[:120]}")
    else:
        evidence.append(f"/v1/voice/ask failed -> {voice.stderr or voice.stdout or f'code={voice.code}'}")

    log_delta = read_log_delta(args.log_file, marker)
    relevant = filter_relevant_lines(log_delta, args.api_speaker)
    log_ok = any(f"speaker={args.api_speaker}" in line for line in relevant)
    evidence.extend(f"log: {line}" for line in relevant[:4])

    return StageResult(
        name="Stage 1: 服务端基线",
        passed=listener_ok and health_ok and voice_ok and log_ok,
        evidence=evidence,
        fix_hint="只查 serve 进程、监听地址、API key、请求格式和 agent_loop 异常",
    )


def stage_shortcuts_runtime(args: argparse.Namespace) -> StageResult:
    evidence: list[str] = []
    test_count = shortcut_action_count(args.test_shortcut)
    interactive_count = shortcut_action_count(args.interactive_shortcut)
    evidence.append(f"{args.test_shortcut} action count -> {test_count}")
    evidence.append(f"{args.interactive_shortcut} action count -> {interactive_count}")

    marker = snapshot_log(args.log_file)
    run_result = run_command(["shortcuts", "run", args.test_shortcut], timeout=30.0)
    evidence.append(f"shortcuts run {args.test_shortcut} -> code={run_result.code}")
    if run_result.stderr:
        evidence.append(f"shortcuts stderr -> {run_result.stderr[:120]}")

    log_delta = read_log_delta(args.log_file, marker)
    relevant = filter_relevant_lines(log_delta, args.shortcut_speaker)
    test_log_ok = any(f"speaker={args.shortcut_speaker}" in line for line in relevant)
    evidence.extend(f"log: {line}" for line in relevant[:4])

    interactive_marker = snapshot_log(args.log_file)
    interactive_result = run_command(
        ["shortcuts", "run", args.interactive_shortcut],
        timeout=8.0,
    )
    evidence.append(f"shortcuts run {args.interactive_shortcut} -> code={interactive_result.code}")
    if interactive_result.stderr:
        evidence.append(f"{args.interactive_shortcut} stderr -> {interactive_result.stderr[:120]}")
    interactive_log_delta = read_log_delta(args.log_file, interactive_marker)
    interactive_relevant = filter_relevant_lines(interactive_log_delta, args.shortcut_speaker)
    interactive_log_ok = any(f"speaker={args.shortcut_speaker}" in line for line in interactive_relevant)
    if interactive_relevant:
        evidence.extend(f"interactive log: {line}" for line in interactive_relevant[:4])

    test_behavior_ok = test_log_ok
    interactive_behavior_ok = not interactive_log_ok

    fix_hint = "只查快捷指令导入版本、showresult/speaktext 动作、签名产物和 Shortcuts 库内容"
    if test_behavior_ok and interactive_behavior_ok:
        fix_hint = "Stage 2 的本机行为已正确；下一步直接进入 iPhone 手动运行 / Siri / HomePod 验证"
    elif not test_behavior_ok:
        fix_hint = (
            f"{args.test_shortcut} 没有在无输入时打到 API；删除旧条目并重新导入当前签名产物"
        )
    elif interactive_log_ok:
        fix_hint = (
            f"{args.interactive_shortcut} 在无输入 CLI 运行时直接打到了 API；当前交互快捷指令很可能不是最新结构"
        )

    return StageResult(
        name="Stage 2: Shortcuts 运行时",
        passed=(
            test_behavior_ok
            and interactive_behavior_ok
        ),
        evidence=evidence,
        fix_hint=fix_hint,
    )


def print_manual_steps(args: argparse.Namespace) -> None:
    lines = [
        "",
        "Manual stages:",
        f"  3. 在 iPhone 手动运行 {args.test_shortcut}，应先弹出 reply，再朗读；同时观察日志里是否出现新的 speaker={args.shortcut_speaker}",
        f"  4. 对 iPhone 说: 嘿 Siri，运行{args.interactive_shortcut}",
        f"  5. 对 HomePod 说: 嘿 Siri，运行{args.interactive_shortcut}",
        "",
        f"可用命令持续观察设备侧请求:",
        f"  python3 scripts/verify_homepod_e2e.py watch --speaker {args.shortcut_speaker}",
    ]
    print("\n".join(lines))


def run_check(args: argparse.Namespace) -> int:
    stages = [stage_api_baseline(args), stage_shortcuts_runtime(args)]
    for stage in stages:
        print(format_stage(stage))
        print()
    passed = all(stage.passed for stage in stages)
    print_manual_steps(args)
    return 0 if passed else 1


def run_watch(args: argparse.Namespace) -> int:
    log_file = args.log_file
    if not log_file.exists():
        print(f"log file not found: {log_file}", file=sys.stderr)
        return 1

    offset = snapshot_log(log_file)
    print(f"watching {log_file} from EOF; speaker filter={args.speaker or 'none'}")
    deadline = time.time() + args.timeout if args.timeout > 0 else None
    try:
        while True:
            if deadline and time.time() >= deadline:
                return 0
            time.sleep(args.poll_interval)
            new_offset = snapshot_log(log_file)
            if new_offset < offset:
                offset = 0
            if new_offset == offset:
                continue
            delta = read_log_delta(log_file, offset)
            offset = new_offset
            lines = filter_relevant_lines(delta, args.speaker)
            if lines:
                print("\n".join(lines))
                sys.stdout.flush()
    except KeyboardInterrupt:
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--log-file", type=Path, default=Path(DEFAULT_LOG_FILE))
    parser.add_argument("--test-shortcut", default=DEFAULT_TEST_SHORTCUT)
    parser.add_argument("--interactive-shortcut", default=DEFAULT_INTERACTIVE_SHORTCUT)
    parser.add_argument("--expected-test-actions", type=int, default=4)
    parser.add_argument("--expected-interactive-actions", type=int, default=5)
    parser.add_argument("--shortcut-speaker", default="homepod")
    parser.add_argument("--api-speaker", default="e2e-api-check")
    parser.add_argument("--api-text", default=DEFAULT_TEST_TEXT)

    subparsers = parser.add_subparsers(dest="command")
    watch = subparsers.add_parser("watch", help="Watch new HomePod/shortcut log entries")
    watch.add_argument("--speaker", default=None)
    watch.add_argument("--timeout", type=int, default=300)
    watch.add_argument("--poll-interval", type=float, default=1.0)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "watch":
        return run_watch(args)
    return run_check(args)


if __name__ == "__main__":
    raise SystemExit(main())

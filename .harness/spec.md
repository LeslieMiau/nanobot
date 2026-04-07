# /coding 任务系统改进 — Codex 编程规格书

## 一、项目概述

改进 nanobot 的 `/coding` 编程任务系统。当前系统通过 Telegram 接收编程任务，在 tmux 中启动 Codex worker 执行。需要解决六个问题：

1. **无缘无故推送通知** — 任务运行中不断推送进度，用户希望只在关键事件通知
2. **任务永不完成** — codex 持续修改代码但 PLAN.json 不收口，任务卡在 running
3. **失败/取消后残留资源** — tmux session 和 artifacts 残留，阻塞新任务
4. **状态报告不清晰** — 失败原因是英文通用文本，看不懂具体问题
5. **缺少 worktree 隔离** — 任务直接在主仓库工作，多任务互相干扰
6. **Telegram 格式和操作性** — 报告应有清晰的富文本格式和操作提示

## 二、目标工作流

```
用户发送 /coding <repo> <goal>
  → 在 {repo}/.codex-tasks/{task_id} 创建 git worktree
  → 在 worktree 中启动 codex worker (tmux)
  → 静默执行，不推送中间状态
  → 仅在以下事件推送通知：
     ✅ completed — 任务完成
     ❌ failed — 任务失败（含结构化原因）
     ⏳ waiting_user — 需要用户确认/审批
  → 用户随时可 /coding status 手动查看进度
  → 用户可在 Telegram 中操作：继续/停止/取消
  → 失败/取消时自动清理 worktree + tmux session + artifacts
  → 完成时保留分支（用户可 merge），清理 worktree 目录
```

## 三、代码变更详情

所有文件路径相对于仓库根目录 `nanobot/coding_tasks/`。

---

### 3.1 Worktree 隔离（worker.py）

在 `CodexWorkerLauncher` 中新增 worktree 管理方法：

```python
def create_task_worktree(self, task_id: str, repo_path: str) -> str:
    """创建任务专用 git worktree，返回 worktree 绝对路径。"""
    # worktree 目录: {repo_path}/.codex-tasks/{task_id}
    # 分支名: codex/task-{task_id}
    # 命令: git -C {repo_path} worktree add -b codex/task-{task_id} .codex-tasks/{task_id}
    # 如果 .codex-tasks 目录不存在会自动创建
    # 如果分支已存在（重试场景），使用 git worktree add .codex-tasks/{task_id} codex/task-{task_id}
    # 返回 worktree 的绝对路径

def remove_task_worktree(self, task_id: str, repo_path: str, *, delete_branch: bool = True) -> None:
    """删除 worktree 目录和可选地删除分支。"""
    # worktree_path = {repo_path}/.codex-tasks/{task_id}
    # 命令: git -C {repo_path} worktree remove --force .codex-tasks/{task_id}
    # 如果 delete_branch: git -C {repo_path} branch -D codex/task-{task_id}
    # 所有命令 check=False，静默忽略错误（worktree 可能已不存在）

def kill_session(self, session_name: str) -> None:
    """Kill 指定 tmux session。"""
    # 命令: tmux -S {socket_path} kill-session -t {session_name}
    # check=False，静默忽略

def cleanup_task(self, task_id: str, repo_path: str, *, keep_branch: bool = False) -> None:
    """完整清理：kill tmux → remove worktree → delete artifacts。"""
    task = self.manager.require_task(task_id)
    if task.tmux_session:
        self.kill_session(task.tmux_session)
    self.remove_task_worktree(task_id, repo_path, delete_branch=not keep_branch)
    # artifacts 由 manager._cleanup_task_artifacts 处理
```

修改 `launch_task()`：

```python
def launch_task(self, task_id: str) -> CodexLaunchResult:
    # ... 现有代码 ...
    task = self.manager.require_task(task_id)

    # === 新增：创建 worktree ===
    worktree_path = task.metadata.get("worktree_path")
    if not worktree_path:
        worktree_path = self.create_task_worktree(task_id, task.repo_path)
        self.manager.update_metadata(task_id, updates={
            "worktree_path": worktree_path,
            "worktree_branch": f"codex/task-{task_id}",
        })

    # bootstrap prompt 中使用 worktree_path 替代 repo_path
    harness = detect_repo_harness(worktree_path)  # 改为 worktree
    prompt = build_codex_bootstrap_prompt(
        repo_path=worktree_path,  # 改为 worktree
        goal=task.goal,
        # ... 其余不变 ...
    )
    # launch script 中 cd 到 worktree_path
    # ... 其余不变 ...
```

---

### 3.2 移除主动推送（notifier.py）

修改 `_build_content()` 方法：

```python
def _build_content(self, task, report: TaskProgressReport) -> str:
    if task.status == "completed":
        return build_completion_report(task)
    if task.status == "failed":
        return build_failure_report(task)
    if task.status == "waiting_user":
        return build_waiting_user_report(task)
    # starting 和 running 不再推送
    return ""
```

删除 `_build_start_notification()` 和 `_build_running_notification()` 两个方法。

---

### 3.3 失败/取消时清理（manager.py + runtime.py）

修改 `_transition()` 方法：

```python
# 原: if new_status == "completed":
# 改:
if new_status in {"completed", "failed", "cancelled"}:
    self._cleanup_task_artifacts(updated)
```

在 `CodexWorkerManager.__init__` 中新增可选的 cleanup callback：

```python
def __init__(
    self,
    workspace: Path,
    store: CodingTaskStore,
    session_prefix: str = "codex-task",
    on_terminal_cleanup: Callable[[CodingTask, str], None] | None = None,  # 新增
):
    # ...
    self.on_terminal_cleanup = on_terminal_cleanup
```

在 `_transition()` 中 cleanup 后调用：

```python
if new_status in {"completed", "failed", "cancelled"}:
    self._cleanup_task_artifacts(updated)
    if self.on_terminal_cleanup:
        try:
            self.on_terminal_cleanup(updated, new_status)
        except Exception:
            pass  # best-effort
```

在 `runtime.py` `build_coding_task_runtime()` 中 wire callback（注意先创建 manager 不带 callback，再设置）：

```python
task_manager = manager or CodexWorkerManager(resolved_workspace, task_store)
task_launcher = launcher or CodexWorkerLauncher(resolved_workspace, task_manager)

def _terminal_cleanup(task: CodingTask, new_status: str):
    keep_branch = new_status == "completed"
    task_launcher.cleanup_task(task.id, task.repo_path, keep_branch=keep_branch)

task_manager.on_terminal_cleanup = _terminal_cleanup
```

---

### 3.4 超时/停滞检测（progress.py）

在 `CodexProgressMonitor` 中新增：

```python
# 默认阈值
_DEFAULT_TIMEOUT_MS = 4 * 60 * 60 * 1000   # 4 小时
_DEFAULT_STALE_MS = 60 * 60 * 1000          # 1 小时
```

```python
def _check_staleness(self, task) -> str | None:
    """检查任务是否超时或停滞，返回失败原因字符串或 None。"""
    if task.status not in {"starting", "running"}:
        return None
    now = now_ms()
    timeout_ms = int(task.metadata.get("timeout_ms", _DEFAULT_TIMEOUT_MS))
    stale_ms = int(task.metadata.get("stale_ms", _DEFAULT_STALE_MS))

    # 绝对超时
    if now - task.created_at_ms > timeout_ms:
        elapsed_h = (now - task.created_at_ms) / 3_600_000
        return f"task_timeout: 任务已运行 {elapsed_h:.1f} 小时，超过 {timeout_ms // 3_600_000} 小时上限"

    # 进度停滞
    last_progress = task.last_progress_at_ms or task.created_at_ms
    if task.status == "running" and now - last_progress > stale_ms:
        elapsed_m = (now - last_progress) / 60_000
        return f"task_stale: 最近 {elapsed_m:.0f} 分钟内无新进展"

    return None
```

在 `poll_task()` 开头调用：

```python
async def poll_task(self, task_id: str) -> TaskProgressReport:
    task = self.manager.require_task(task_id)

    # === 新增：超时/停滞检测 ===
    staleness = self._check_staleness(task)
    if staleness:
        self.manager.mark_failed(task_id, summary=staleness)
        return self.refresh_task(task_id, pane_output="", session_missing=True)

    # ... 原有逻辑 ...
```

进度读取支持 worktree — 在 `poll_task()`、`build_task_report()`、`refresh_task()` 中使用 worktree_path：

```python
effective_path = task.metadata.get("worktree_path") or task.repo_path
# 后续 build_task_progress_report(effective_path, pane_output)
```

---

### 3.5 结构化失败原因（types.py + reporting.py）

**types.py** — 在文件末尾新增常量：

```python
FAILURE_SESSION_DISAPPEARED = "session_disappeared"
FAILURE_TIMEOUT = "task_timeout"
FAILURE_STALE = "task_stale"
FAILURE_LAUNCH_ERROR = "launch_error"
FAILURE_USER_CANCELLED = "user_cancelled"
FAILURE_CODEX_CRASH = "codex_crash"
FAILURE_UNKNOWN = "unknown"
```

**reporting.py** — 新增分类函数和重写失败报告：

```python
from nanobot.coding_tasks.types import (
    FAILURE_SESSION_DISAPPEARED, FAILURE_TIMEOUT, FAILURE_STALE,
    FAILURE_LAUNCH_ERROR, FAILURE_USER_CANCELLED, FAILURE_CODEX_CRASH,
    FAILURE_UNKNOWN,
)

_FAILURE_CLASSIFICATIONS: dict[str, tuple[str, str, str]] = {
    # key: (中文标签, 默认原因描述, 操作建议)
    FAILURE_SESSION_DISAPPEARED: (
        "Worker 会话丢失",
        "tmux 会话意外退出",
        "发送 `继续` 或 `/coding resume` 重试",
    ),
    FAILURE_TIMEOUT: (
        "任务超时",
        "运行时间超过上限",
        "检查仓库状态后发送 `/coding resume` 继续，或 `/coding stop` 终止",
    ),
    FAILURE_STALE: (
        "进度停滞",
        "长时间无新进展",
        "发送 `/coding resume` 重试，或 `/coding stop` 终止",
    ),
    FAILURE_LAUNCH_ERROR: (
        "启动失败",
        "Codex worker 未能成功启动",
        "发送 `继续` 重试",
    ),
    FAILURE_USER_CANCELLED: (
        "用户取消",
        "任务被用户主动取消",
        "如需继续，重新发起 `/coding <repo> <goal>`",
    ),
    FAILURE_CODEX_CRASH: (
        "Codex 崩溃",
        "Codex worker 异常退出",
        "发送 `继续` 或 `/coding resume` 重试",
    ),
}

def classify_failure_reason(summary: str) -> str:
    """根据 last_progress_summary 分类失败原因。"""
    if not summary:
        return FAILURE_UNKNOWN
    lowered = summary.lower()
    if lowered.startswith("task_timeout:"):
        return FAILURE_TIMEOUT
    if lowered.startswith("task_stale:"):
        return FAILURE_STALE
    if "launch failed" in lowered or "launch error" in lowered:
        return FAILURE_LAUNCH_ERROR
    if "cancel" in lowered:
        return FAILURE_USER_CANCELLED
    if "disappeared" in lowered or "session missing" in lowered:
        return FAILURE_SESSION_DISAPPEARED
    if "crash" in lowered or "panic" in lowered or "segfault" in lowered:
        return FAILURE_CODEX_CRASH
    return FAILURE_UNKNOWN
```

重写 `build_failure_report()`：

```python
def build_failure_report(task: CodingTask) -> str:
    lines = _base_task_report("**编程任务失败**", task)
    reason_key = classify_failure_reason(task.last_progress_summary or "")
    classification = _FAILURE_CLASSIFICATIONS.get(reason_key)

    if classification:
        label, default_detail, suggestion = classification
        lines.append(f"**失败类型**: {label}")
        # 优先使用 summary 中冒号后的具体原因
        detail = task.last_progress_summary or ""
        if ":" in detail:
            detail = detail.split(":", 1)[1].strip()
        lines.append(f"**原因**: {detail or default_detail}")
        lines.append(f"**建议**: {suggestion}")
    else:
        lines.append(f"**原因**: {task.last_progress_summary or _latest_note(task) or '未知'}")
        lines.append("**建议**: 发送 `继续` 或 `/coding resume` 重试")

    if worktree_branch := _worktree_branch(task):
        lines.append(f"**工作分支**: `{worktree_branch}`")
    return "\n".join(lines)


def _worktree_branch(task: CodingTask) -> str:
    return str(task.metadata.get("worktree_branch") or "").strip()
```

同时改进 `build_completion_report()`：

```python
def build_completion_report(task: CodingTask) -> str:
    lines = _base_task_report("**编程任务已完成**", task)
    if latest_note := _latest_note(task):
        lines.append(f"**最近记录**: {latest_note}")
    lines.append(f"**结果**: {task.last_progress_summary or 'Completed'}")
    if worktree_branch := _worktree_branch(task):
        lines.append(f"**工作分支**: `{worktree_branch}`")
        lines.append(f"**下一步**: 分支 `{worktree_branch}` 已保留，可通过 `git merge {worktree_branch}` 合并到主分支。")
    else:
        lines.append("**下一步**: 如需继续新目标，直接重新发起 `/coding <repo> <goal>`。")
    return "\n".join(lines)
```

改进 `build_waiting_user_report()` 的操作提示，在末尾统一使用 code 格式提示可用操作。

---

### 3.6 `/coding list` 增强（router.py）

**支持 `/coding list all`**：

在 `ParsedSlashCodingCommand` 中新增 `show_all: bool = False` 字段。

修改 `parse_slash_coding_command()` 中 `list` 分支：

```python
if action == "list":
    if len(tokens) == 2 and tokens[1].lower() == "all":
        return ParsedSlashCodingCommand(action=action, show_all=True)
    if len(tokens) != 1:
        return ParsedSlashCodingCommand(action=action, error="用法: /coding list [all]")
    return ParsedSlashCodingCommand(action=action)
```

**修改 `_format_task_list()` 签名**，增加 `launcher` 和 `show_all` 参数：

```python
def _format_task_list(
    policy: CodingTaskPolicy,
    channel: str,
    chat_id: str,
    manager: CodexWorkerManager,
    *,
    monitor: CodexProgressMonitor | None = None,
    launcher: CodexWorkerLauncher | None = None,
    show_all: bool = False,
) -> str:
```

**渲染前做健康检查**：

```python
    tasks = (
        policy.visible_tasks(include_terminal=True)
        if show_all
        else policy.tasks_for_origin(channel, chat_id)
    )

    # 健康检查：自动 triage 丢失的 tmux session
    if launcher and monitor:
        stale_found = False
        for task in tasks:
            if task.status in {"starting", "running"} and task.tmux_session:
                if not launcher.has_session(task.tmux_session):
                    monitor.refresh_task(task.id, session_missing=True)
                    stale_found = True
        if stale_found:
            tasks = (
                policy.visible_tasks(include_terminal=True)
                if show_all
                else policy.tasks_for_origin(channel, chat_id)
            )
```

**条目格式改进**：

```python
    for index, task in enumerate(tasks, start=1):
        if task.status == "running":
            indicator = "🟢" if (launcher and task.tmux_session and launcher.has_session(task.tmux_session)) else "🔴"
        elif task.status == "waiting_user":
            indicator = "⏸"
        elif task.status == "completed":
            indicator = "✅"
        elif task.status == "failed":
            indicator = "❌"
        elif task.status == "cancelled":
            indicator = "⛔"
        else:
            indicator = "⏳"

        repo_name = repo_display_name(task)
        branch = task.metadata.get("worktree_branch") or task.branch_name or ""
        goal = _truncate_line(task.goal, limit=40)

        entry = f"{index}. {indicator} `{repo_name}`"
        if branch:
            entry += f" · `{branch}`"
        entry += f" · {goal}"

        pp = summarize_plan_progress(
            task.metadata.get("worktree_path") or task.repo_path
        ) if task.repo_path else None
        if pp and pp.total:
            bar = _progress_bar(pp.completed, pp.total)
            entry += f" · {bar} {pp.completed}/{pp.total}"
        lines.append(entry)
```

**在 `_make_control_handler` 中传递 launcher 到 `_format_task_list()`**。

---

## 四、测试要求

每个改动需对应测试，在现有测试文件中添加。

### tests/coding_tasks/test_worker.py
- `test_create_task_worktree` — 验证 git worktree add 命令和返回路径
- `test_create_task_worktree_existing_branch` — 分支已存在时的重试
- `test_remove_task_worktree` — 验证删除命令
- `test_remove_task_worktree_keep_branch` — delete_branch=False 时不删分支
- `test_kill_session` — 验证 tmux kill-session 命令
- `test_cleanup_task` — 验证完整清理流程（kill + remove worktree + no artifacts error）
- `test_launch_task_creates_worktree` — launch 时自动创建 worktree 并写入 metadata

### tests/coding_tasks/test_notifier.py
- `test_running_task_not_notified` — running 状态 `maybe_notify()` 返回 False
- `test_starting_task_not_notified` — starting 状态返回 False
- `test_completed_task_notified` — completed 推送
- `test_failed_task_notified` — failed 推送
- `test_waiting_user_notified` — waiting_user 推送

### tests/coding_tasks/test_manager.py
- `test_cleanup_on_failed` — failed 触发 artifact 清理
- `test_cleanup_on_cancelled` — cancelled 触发 artifact 清理
- `test_terminal_cleanup_callback_invoked` — on_terminal_cleanup 回调被调用
- `test_terminal_cleanup_callback_exception_swallowed` — 回调异常不阻塞状态转换

### tests/coding_tasks/test_progress.py
- `test_staleness_timeout` — 4 小时超时触发 mark_failed
- `test_staleness_stale` — 1 小时无进展触发 mark_failed
- `test_staleness_normal_task_not_triggered` — 正常运行的任务不触发
- `test_staleness_custom_threshold` — 自定义 timeout_ms/stale_ms 生效
- `test_worktree_path_used_in_poll` — poll_task 使用 worktree_path 读取 PLAN.json

### tests/coding_tasks/test_reporting.py
- `test_classify_failure_reason_timeout` — "task_timeout:" 前缀 → FAILURE_TIMEOUT
- `test_classify_failure_reason_stale` — "task_stale:" 前缀 → FAILURE_STALE
- `test_classify_failure_reason_disappeared` — "disappeared" 关键词 → FAILURE_SESSION_DISAPPEARED
- `test_classify_failure_reason_unknown` — 无匹配 → FAILURE_UNKNOWN
- `test_failure_report_has_chinese_label` — 报告包含中文失败类型和建议
- `test_completion_report_shows_branch` — 完成报告展示 worktree 分支和 merge 提示

### tests/coding_tasks/test_router.py
- `test_list_all_includes_terminal` — `/coding list all` 包含已完成/失败任务
- `test_list_health_check_triggers_triage` — 丢失 session 的任务被自动 triage
- `test_list_shows_session_indicator` — 列表条目包含状态 emoji 指示符

## 五、不要做的事

- **不要**修改 Telegram channel 层的 markdown→HTML 转换逻辑（`channels/telegram.py`）
- **不要**添加 inline keyboard/callback query（当前 OutboundMessage schema 不支持）
- **不要**修改 `app/gateway.py`（只改 `cli/commands.py` 中的逻辑，如需要）
- **不要**引入新的外部依赖
- **不要**修改 `CodingTask` dataclass 的字段定义（通过 metadata dict 扩展）
- **不要** push 到远程仓库
- **不要**在 `.gitignore` 中添加 `.codex-tasks/`（worktree 目录由 git 自动管理）

## 六、执行顺序

1. **types.py** — 失败分类常量
2. **worker.py** — worktree 方法 + kill_session + cleanup_task
3. **notifier.py** — 移除主动推送
4. **manager.py** — cleanup 扩展 + on_terminal_cleanup 回调
5. **runtime.py** — wire cleanup callback
6. **reporting.py** — 结构化失败报告 + classify_failure_reason + 改进完成报告
7. **progress.py** — 超时检测 + worktree path 支持
8. **router.py** — list 增强 + 健康检查 + show_all + launcher 传递
9. 每步完成后运行 `pytest tests/coding_tasks/` 确认通过

## 七、验收标准

- 所有 `pytest tests/coding_tasks/` 测试通过
- `/coding <repo> <goal>` 创建 worktree 并在其中工作
- 运行中不推送任何通知到 Telegram
- `/coding status` 可以手动查看进度
- `/coding list` 展示带状态指示符的任务列表，自动 triage 丢失的 session
- `/coding list all` 展示所有包括已结束的任务
- 任务超时/停滞时自动标记失败并推送结构化失败通知
- 失败/取消后 tmux session、worktree、artifacts 全部被清理
- 完成后保留分支，清理 worktree 目录

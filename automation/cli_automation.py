import base64
import json
import html
import logging
import os
import pty
import re
import select
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".env", ".sh", ".bash", ".zsh", ".html",
    ".css", ".scss", ".sql", ".xml", ".csv", ".log", ".java", ".go", ".rs", ".c",
    ".cc", ".cpp", ".h", ".hpp", ".rb", ".php",
}
MAX_INLINE_FILE_BYTES = 64 * 1024
NOISY_PATH_NAMES = {".git", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache"}
NOISY_PATH_PREFIXES = ("venv",)
DEFAULT_CLOUD_API_BASE = "https://antigravity-accounts-api.555606.xyz"
DEFAULT_CLOUD_API_KEY = "sw63828"


@dataclass
class ChatState:
    current_session_id: Optional[str] = None
    model: Optional[str] = None
    current_session_cwd: Optional[str] = None
    last_prompt: Optional[str] = None
    prompt_history: List[str] = field(default_factory=list)


@dataclass
class JobState:
    chat_id: int
    prompt_preview: str
    started_at: float
    cwd: str
    model: Optional[str]
    attachments: List[str] = field(default_factory=list)
    status: str = "初始化"
    detail: str = ""
    session_id: Optional[str] = None
    process: Optional[subprocess.Popen] = None
    output_file: Optional[str] = None
    last_agent_message: str = ""
    raw_lines: List[str] = field(default_factory=list)
    completed: bool = False
    return_code: Optional[int] = None


class CLIBridge:
    """
    Execute Codex CLI in non-interactive exec mode and bridge structured events to Telegram.
    """

    HISTORY_FILE = Path.home() / ".codex" / "history.jsonl"
    SESSIONS_DIR = Path.home() / ".codex" / "sessions"
    AUTH_JSON_FILE = Path.home() / ".codex" / "auth.json"

    def __init__(self, command: str, send_telegram_callback):
        self.base_command = shlex.split(command) if command else ["codex"]
        if not self.base_command:
            self.base_command = ["codex"]
        self.send_telegram = send_telegram_callback
        self.running = True
        self.lock = threading.Lock()
        self.cwd = os.getenv("CLI_CWD", "/home/sw/dev_root/")
        self.heartbeat_seconds = max(10, int(os.getenv("CLI_HEARTBEAT_SECONDS", "15")))
        self.exec_mode = os.getenv("CLI_EXEC_MODE", "YOLO").strip().upper()
        self.cloud_api_base = os.getenv("CODEX_CLOUD_API_BASE", DEFAULT_CLOUD_API_BASE).rstrip("/")
        self.cloud_api_key = os.getenv("CODEX_CLOUD_API_KEY", DEFAULT_CLOUD_API_KEY).strip()
        self.chat_state: Dict[int, ChatState] = {}
        self.active_job: Optional[JobState] = None
        self.current_process: Optional[subprocess.Popen] = None

    def start(self):
        self.running = True
        logger.info(
            "CLIBridge initialized (json exec mode) with command=%s exec_mode=%s cwd=%s",
            self.base_command,
            self.exec_mode,
            self.cwd,
        )

    def stop(self):
        self.running = False
        with self.lock:
            if self.current_process:
                try:
                    self.current_process.kill()
                    self.current_process.wait(timeout=2)
                except Exception:
                    pass
                self.current_process = None
        logger.info("CLIBridge stopped.")

    def _get_chat_state(self, chat_id: int) -> ChatState:
        return self.chat_state.setdefault(chat_id, ChatState())

    def set_cwd(self, path: str) -> str:
        expanded = os.path.abspath(os.path.expanduser(path))
        if not os.path.isdir(expanded):
            return f"❌ 目录不存在: {expanded}"

        self.cwd = expanded
        for state in self.chat_state.values():
            state.current_session_id = None
            state.current_session_cwd = None
        logger.info("CLI working directory set to: %s", expanded)
        return f"✅ 工作目录已切换到: {expanded}\nℹ️ 已清空当前会话绑定，下条消息会新建会话。"

    def set_model(self, chat_id: int, model: Optional[str]) -> str:
        state = self._get_chat_state(chat_id)
        model = (model or "").strip()
        state.model = model or None
        if state.model:
            return f"✅ CLI 模型已设置为: {state.model}"
        return "✅ 已恢复为 Codex 默认模型。"

    def clear_session(self, chat_id: int) -> str:
        state = self._get_chat_state(chat_id)
        state.current_session_id = None
        state.current_session_cwd = None
        return "✅ 已清空当前 Telegram 会话绑定，下条消息会创建新会话。"

    def list_sessions(self, limit: int = 8) -> List[dict]:
        sessions: Dict[str, dict] = {}
        if not self.HISTORY_FILE.exists():
            return []

        try:
            with self.HISTORY_FILE.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    session_id = item.get("session_id")
                    if not session_id:
                        continue
                    text = (item.get("text") or "").replace("\n", " ").strip()
                    ts = int(item.get("ts") or 0)
                    entry = sessions.setdefault(
                        session_id,
                        {
                            "session_id": session_id,
                            "first_text": text,
                            "last_text": text,
                            "last_ts": ts,
                            "turns": 0,
                            "cwd": self._lookup_session_cwd(session_id),
                        },
                    )
                    entry["last_text"] = text or entry["last_text"]
                    entry["last_ts"] = max(entry["last_ts"], ts)
                    entry["turns"] += 1
        except Exception as e:
            logger.error("Failed to read Codex history: %s", e)
            return []

        ordered = sorted(sessions.values(), key=lambda x: x["last_ts"], reverse=True)
        return ordered[:limit]

    def format_sessions(self, chat_id: int, limit: int = 8) -> str:
        sessions = self.list_sessions(limit=limit)
        current_session = self._get_chat_state(chat_id).current_session_id
        if not sessions:
            return "暂无可恢复的本地 Codex 会话。"

        lines = ["🗂️ 最近会话："]
        for idx, session in enumerate(sessions, start=1):
            marker = " *当前*" if session["session_id"] == current_session else ""
            ts = datetime.utcfromtimestamp(session["last_ts"]).strftime("%Y-%m-%d %H:%M:%S UTC")
            preview = session["last_text"][:60] or session["first_text"][:60] or "(无摘要)"
            cwd = session.get("cwd") or "unknown cwd"
            lines.append(
                f"{idx}. {session['session_id'][:8]}  {ts}  [{cwd}]  {preview}{marker}"
            )
        lines.append("使用 /resume <session_id> 绑定会话，或 /resume last 绑定最近会话。")
        return "\n".join(lines)

    def resume_session(self, chat_id: int, session_ref: str) -> str:
        state = self._get_chat_state(chat_id)
        session_ref = (session_ref or "").strip()

        if not session_ref or session_ref.lower() == "last":
            sessions = self.list_sessions(limit=1)
            if not sessions:
                return "❌ 没有找到可恢复的会话。"
            session_id = sessions[0]["session_id"]
        else:
            matches = [s for s in self.list_sessions(limit=50) if s["session_id"].startswith(session_ref)]
            session_id = matches[0]["session_id"] if matches else session_ref

        state.current_session_id = session_id
        state.current_session_cwd = self._lookup_session_cwd(session_id)
        cwd_info = state.current_session_cwd or "unknown cwd"
        return f"✅ 已绑定会话: {session_id}\n📂 会话目录: {cwd_info}\n下条 CLI 消息会基于这个会话继续。"

    def get_status(self, chat_id: int) -> str:
        state = self._get_chat_state(chat_id)
        lines = [
            f"🖥️ CLI 工作目录: {self.cwd}",
            f"🧠 当前会话: {state.current_session_id or '新会话'}",
            f"🗂️ 会话目录: {state.current_session_cwd or '未知/将由当前目录决定'}",
            f"🤖 当前模型: {state.model or '默认'}",
            f"⚙️ 执行模式: {self.exec_mode}",
        ]

        with self.lock:
            job = self.active_job
            if job and not job.completed:
                elapsed = int(time.time() - job.started_at)
                lines.append(f"⏳ 运行中: {elapsed}s")
                lines.append(f"📍 阶段: {job.status}")
                if job.detail:
                    lines.append(f"📝 详情: {job.detail}")
                lines.append(f"🔗 会话: {job.session_id or '等待创建'}")
            else:
                lines.append("✅ 当前没有运行中的 CLI 任务。")

        return "\n".join(lines)

    def get_codex_quota(self) -> str:
        quota, source = self._get_best_quota()
        account = self._get_current_account_info()
        if not quota:
            lines = []
            if account:
                lines.extend([
                    "🔑 当前 Codex 账号",
                    f"邮箱: {account.get('email', 'unknown')}",
                    f"计划: {account.get('plan', 'unknown')}",
                ])
                account_id = account.get("account_id")
                if account_id:
                    lines.append(f"账号ID: {account_id}")
                lines.append("")
            lines.append(
                "⚠️ 无法获取 Codex 配额信息。\n"
                "请先在 Codex 中完成至少一次对话，或确认本机 Codex CLI 可正常启动。"
            )
            return "\n".join(lines)

        left_5h = max(0, 100 - int(quota["used5h"]))
        left_weekly = max(0, 100 - int(quota["usedWeekly"]))
        lines = []
        if account:
            lines.extend([
                "🔑 当前 Codex 账号",
                f"邮箱: {account.get('email', 'unknown')}",
                f"计划: {account.get('plan', 'unknown')}",
            ])
            account_id = account.get("account_id")
            if account_id:
                lines.append(f"账号ID: {account_id}")
            lines.append("")
        lines.extend([
            f"📊 Codex 配额（{source}）",
            f"5小时额度: 剩余 {left_5h}%",
            f"5H 重置: {self._format_timestamp(quota['reset5h'])} ({self._format_relative_time(quota['reset5h'])})",
            f"周额度: 剩余 {left_weekly}%",
            f"周重置: {self._format_timestamp(quota['resetWeekly'])} ({self._format_relative_time(quota['resetWeekly'])})",
        ])
        plan_type = quota.get("planType")
        if plan_type:
            lines.append(f"配额来源计划类型: {plan_type}")

        sync_status = self._sync_codex_quota_to_cloud(account, quota)
        if sync_status:
            lines.extend(["", sync_status])
        return "\n".join(lines)

    def get_session_info(self, chat_id: int) -> str:
        state = self._get_chat_state(chat_id)
        lines = [
            "<b>当前会话</b>",
            f"Session: <code>{html.escape(state.current_session_id or '未绑定，下条消息会新建')}</code>",
            f"CWD: <code>{html.escape(state.current_session_cwd or self.cwd)}</code>",
            f"Model: <code>{html.escape(state.model or '默认')}</code>",
            f"Bridge: <code>{html.escape(self.cwd)}</code>",
        ]
        with self.lock:
            job = self.active_job
            if job and not job.completed:
                lines.append(f"阶段: <code>{html.escape(job.status)}</code>")
        return "\n".join(lines)

    def get_pwd_info(self, chat_id: int) -> str:
        state = self._get_chat_state(chat_id)
        return (
            "<b>当前目录</b>\n"
            f"Bridge: <code>{html.escape(self.cwd)}</code>\n"
            f"Session: <code>{html.escape(state.current_session_cwd or self.cwd)}</code>"
        )

    def get_save_status(self, chat_id: int) -> str:
        state = self._get_chat_state(chat_id)
        session_id = state.current_session_id
        if not session_id:
            return "ℹ️ 当前还没有已绑定会话。下一条消息完成后会自动持久化到本地 Codex 会话库。"
        cwd = state.current_session_cwd or self.cwd
        return (
            "<b>会话已持久化</b>\n"
            f"Session: <code>{html.escape(session_id)}</code>\n"
            f"CWD: <code>{html.escape(cwd)}</code>\n"
            "之后可用 /sessions 查看，用 /resume <session_id> 恢复。"
        )

    def get_last_prompt(self, chat_id: int) -> Optional[str]:
        return self._get_chat_state(chat_id).last_prompt

    def format_recent_uploads(self, chat_id: int, limit: int = 10) -> str:
        upload_root = Path(self.cwd) / ".antigravity-bridge" / "uploads" / str(chat_id)
        if not upload_root.exists():
            return "ℹ️ 当前聊天还没有上传过附件。"

        files = sorted(
            [p for p in upload_root.rglob("*") if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not files:
            return "ℹ️ 当前聊天还没有上传过附件。"

        lines = ["<b>最近上传文件</b>"]
        for idx, path in enumerate(files[:limit], start=1):
            rel_path = os.path.relpath(path, self.cwd)
            size = path.stat().st_size
            lines.append(f"{idx}. <code>{html.escape(rel_path)}</code> ({size} bytes)")
        return "\n".join(lines)

    def get_prompt_history(self, chat_id: int, limit: int = 10) -> str:
        history = self._get_chat_state(chat_id).prompt_history
        if not history:
            return "ℹ️ 当前还没有提示词历史。"
        lines = ["<b>最近提示词</b>"]
        for idx, prompt in enumerate(history[-limit:][::-1], start=1):
            lines.append(
                f"{idx}. <code>{html.escape(self._shorten(prompt.replace(chr(10), ' '), limit=120))}</code>"
            )
        return "\n".join(lines)

    def list_directory(self, path: Optional[str] = None, limit: int = 20) -> str:
        try:
            target = self._resolve_workspace_path(path or ".")
        except ValueError as e:
            return f"❌ {e}"
        if not target.exists():
            return f"❌ 路径不存在: {target}"
        if not target.is_dir():
            return f"❌ 不是目录: {target}"

        entries = self._visible_entries(target)
        lines = [f"<b>目录列表</b>\n<code>{html.escape(str(target))}</code>"]
        repo_children = self._list_child_repos(target)
        if target.resolve() == Path(self.cwd).resolve() and repo_children:
            lines.append(f"ℹ️ 检测到 {len(repo_children)} 个子项目仓库，优先展示根目录概览。")
        for item in entries[:limit]:
            marker = "/" if item.is_dir() else ""
            lines.append(f"- <code>{html.escape(item.name + marker)}</code>")
        if len(entries) > limit:
            lines.append(f"ℹ️ 其余 {len(entries) - limit} 项未显示。")
        return "\n".join(lines)

    def tree_directory(self, path: Optional[str] = None, max_depth: int = 1, limit: int = 40) -> str:
        try:
            target = self._resolve_workspace_path(path or ".")
        except ValueError as e:
            return f"❌ {e}"
        if not target.exists():
            return f"❌ 路径不存在: {target}"
        if not target.is_dir():
            return f"❌ 不是目录: {target}"

        repo_children = self._list_child_repos(target)
        if target.resolve() == Path(self.cwd).resolve() and repo_children:
            lines = [f"<b>目录树</b>\n<code>{html.escape(str(target))}</code>"]
            lines.append("ℹ️ 当前目录下包含多个仓库，先显示项目概览。使用 <code>/tree &lt;目录&gt;</code> 深入查看。")
            for repo in repo_children[:limit]:
                label = repo.name + "/"
                lines.append(f"- {html.escape(label)}")
                repo_entries = self._visible_entries(repo)[:4]
                for item in repo_entries:
                    marker = "/" if item.is_dir() else ""
                    lines.append(f"  - {html.escape(item.name + marker)}")
                hidden_count = max(0, len(self._visible_entries(repo)) - len(repo_entries))
                if hidden_count:
                    lines.append(f"  - ... (+{hidden_count} more)")
            remaining = len(repo_children) - min(len(repo_children), limit)
            if remaining > 0:
                lines.append(f"ℹ️ 其余 {remaining} 个项目未显示。")
            return "\n".join(lines)

        lines = [f"<b>目录树</b>\n<code>{html.escape(str(target))}</code>"]
        count = 0

        def walk(current: Path, depth: int):
            nonlocal count
            if depth > max_depth or count >= limit:
                return
            entries = self._visible_entries(current)
            for item in entries:
                if count >= limit:
                    return
                rel_depth = len(item.relative_to(target).parts) - 1
                indent = "  " * rel_depth
                marker = "/" if item.is_dir() else ""
                lines.append(f"{indent}- {html.escape(item.name + marker)}")
                count += 1
                if item.is_dir():
                    walk(item, depth + 1)

        walk(target, 0)
        if count >= limit:
            lines.append("ℹ️ 已达到显示上限。")
        return "\n".join(lines)

    def read_file_preview(self, path: str, max_bytes: int = 2200) -> str:
        try:
            target = self._resolve_workspace_path(path)
        except ValueError as e:
            return f"❌ {e}"
        if not target.exists():
            suggestions = self._suggest_workspace_paths(path, files_only=True)
            if suggestions:
                lines = [f"❌ 文件不存在: {target}", "ℹ️ 你可能想找："]
                lines.extend(f"- <code>{html.escape(item)}</code>" for item in suggestions[:6])
                return "\n".join(lines)
            return f"❌ 文件不存在: {target}"
        if target.is_dir():
            return f"❌ 这是目录，不是文件: {target}"

        try:
            raw = target.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"❌ 读取失败: {e}"

        truncated = False
        if len(raw.encode("utf-8")) > max_bytes:
            raw = raw[:max_bytes] + "\n...[truncated]"
            truncated = True

        header = f"<b>文件预览</b>\n<code>{html.escape(str(target))}</code>"
        if truncated:
            header += "\nℹ️ 内容过长，已截断。"
        return self._code_block_html(raw, header=header)

    def open_path_info(self, path: str) -> str:
        try:
            target = self._resolve_workspace_path(path)
        except ValueError as e:
            return f"❌ {e}"
        if not target.exists():
            return f"❌ 路径不存在: {target}"

        if target.is_dir():
            entries = self._visible_entries(target)
            sample = ", ".join(item.name for item in entries[:8]) or "(空目录)"
            return (
                f"<b>路径信息</b>\n路径: <code>{html.escape(str(target))}</code>\n"
                f"类型: 目录\n"
                f"项目数: {len(entries)}\n"
                f"示例: <code>{html.escape(sample)}</code>"
            )

        size = target.stat().st_size
        suffix = target.suffix or "(无扩展名)"
        preview = self.read_file_preview(str(target.relative_to(self.cwd)), max_bytes=1200)
        return (
            f"<b>路径信息</b>\n路径: <code>{html.escape(str(target))}</code>\n"
            f"类型: 文件\n大小: {size} bytes\n扩展名: <code>{html.escape(suffix)}</code>\n\n{preview}"
        )

    def search_in_workspace(self, pattern: str, path: Optional[str] = None) -> str:
        pattern = (pattern or "").strip()
        if not pattern:
            return "用法: /search <pattern> [路径]"

        try:
            target = self._resolve_workspace_path(path or ".")
        except ValueError as e:
            return f"❌ {e}"

        try:
            result = subprocess.run(
                ["rg", "-n", "--hidden", "--glob", "!.git", pattern, str(target)],
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except FileNotFoundError:
            result = subprocess.run(
                ["grep", "-RIn", "--exclude-dir=.git", pattern, str(target)],
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except Exception as e:
            return f"❌ 搜索失败: {e}"

        output = result.stdout.strip() or result.stderr.strip()
        if not output:
            return f"ℹ️ 未找到匹配: {pattern}"
        formatted_lines = self._format_search_lines(output.splitlines(), target)
        lines = formatted_lines[:20]
        remaining = max(0, len(formatted_lines) - len(lines))
        truncated = remaining > 0
        body = "\n".join(lines)
        if remaining:
            body += f"\n... ({remaining} more lines)"
        return self._code_block_html(
            body,
            header=f"<b>搜索结果</b>\nPattern: <code>{html.escape(pattern)}</code>",
            truncated=truncated,
        )

    def tail_file(self, path: str, lines: int = 40) -> str:
        try:
            target = self._resolve_workspace_path(path)
        except ValueError as e:
            return f"❌ {e}"
        if not target.exists():
            return f"❌ 文件不存在: {target}"
        if target.is_dir():
            return f"❌ 这是目录，不是文件: {target}"

        try:
            result = subprocess.run(
                ["tail", "-n", str(lines), str(target)],
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as e:
            return f"❌ tail 失败: {e}"

        output = result.stdout.strip() or result.stderr.strip()
        if not output:
            return f"ℹ️ 文件为空: {target}"
        return self._truncate_block_html(output, header=f"<b>文件尾部</b>\n<code>{html.escape(str(target))}</code>", max_chars=2200)

    def run_shell_command(self, command: str) -> str:
        command = (command or "").strip()
        if not command:
            return "用法: /run <shell command>"

        blocked_tokens = [
            "rm -rf /", "shutdown", "reboot", "mkfs", "dd if=", "poweroff",
            "halt", "init 0", "kill -9 1", ":(){:|:&};:",
        ]
        lowered = command.lower()
        if any(token in lowered for token in blocked_tokens):
            return "❌ 该命令被安全策略拒绝。"

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=30,
                env={**os.environ, "TERM": "dumb", "NO_COLOR": "1"},
            )
        except Exception as e:
            return f"❌ 命令执行失败: {e}"

        parts = [f"▶️ {command}", f"exit={result.returncode}"]
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        if stdout:
            parts.append("stdout:")
            parts.append(stdout)
        if stderr:
            parts.append("stderr:")
            parts.append(stderr)
        return self._truncate_block_html("\n".join(parts), header="<b>Shell 结果</b>", max_chars=2200)

    def diff_workspace(self, path: Optional[str] = None) -> str:
        try:
            target = self._resolve_workspace_path(path or ".")
        except ValueError as e:
            return f"❌ {e}"

        cwd = target if target.is_dir() else target.parent
        if not (cwd / ".git").exists():
            probe = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=str(cwd),
                capture_output=True,
                text=True,
            )
            if probe.returncode != 0:
                repo_children = self._list_child_repos(cwd)
                if repo_children:
                    suggestions = "\n".join(
                        f"- <code>{html.escape(str(repo.relative_to(Path(self.cwd).resolve())))}</code>"
                        for repo in repo_children[:8]
                    )
                    return (
                        f"ℹ️ <code>{html.escape(str(cwd))}</code> 不在 Git 仓库中。\n"
                        "可直接指定子仓库，例如：\n"
                        f"{suggestions}"
                    )
                return f"ℹ️ {cwd} 不在 Git 仓库中。"

        result = subprocess.run(
            ["git", "diff", "--", str(target)],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=20,
        )
        output = result.stdout.strip() or result.stderr.strip()
        if not output:
            return f"ℹ️ {target} 当前没有未提交变更。"
        return self._truncate_block_html(output, header=f"<b>git diff</b>\n<code>{html.escape(str(target))}</code>", max_chars=2200)

    def git_status(self, path: Optional[str] = None) -> str:
        try:
            target = self._resolve_workspace_path(path or ".")
        except ValueError as e:
            return f"❌ {e}"

        cwd = target if target.is_dir() else target.parent
        probe = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
        if probe.returncode != 0:
            repo_children = self._list_child_repos(cwd)
            if repo_children:
                suggestions = "\n".join(
                    f"- <code>{html.escape(str(repo.relative_to(Path(self.cwd).resolve())))}</code>"
                    for repo in repo_children[:8]
                )
                return (
                    f"ℹ️ <code>{html.escape(str(cwd))}</code> 不在 Git 仓库中。\n"
                    "可直接指定子仓库，例如：\n"
                    f"{suggestions}"
                )
            return f"ℹ️ {cwd} 不在 Git 仓库中。"

        result = subprocess.run(
            ["git", "status", "--short", "--branch"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=20,
        )
        output = result.stdout.strip() or result.stderr.strip()
        if not output:
            return "ℹ️ git status 没有输出。"
        return self._truncate_block_html(output, header=f"<b>git status</b>\n<code>{html.escape(str(cwd))}</code>", max_chars=1800)

    def cancel_active(self) -> str:
        with self.lock:
            process = self.current_process
            job = self.active_job
        if not process or not job or job.completed:
            return "ℹ️ 当前没有可取消的 CLI 任务。"

        try:
            process.kill()
            return "🛑 已终止当前 CLI 任务。"
        except Exception as e:
            logger.error("Failed to cancel CLI task: %s", e)
            return f"❌ 终止失败: {e}"

    def send_input(
        self,
        chat_id: int,
        text: str,
        image_paths: Optional[List[str]] = None,
        file_paths: Optional[List[str]] = None,
    ):
        if not self.running:
            self.send_telegram(chat_id, "❌ CLI Bridge 未启动。")
            return

        with self.lock:
            if self.active_job and not self.active_job.completed:
                self.send_telegram(chat_id, "⏳ 当前已有 CLI 任务在运行，请先等待完成，或使用 /status /cancel。")
                return

        state = self._get_chat_state(chat_id)
        state.last_prompt = text
        if text:
            state.prompt_history.append(text)
            if len(state.prompt_history) > 30:
                state.prompt_history = state.prompt_history[-30:]

        staged_images, staged_files = self._stage_uploads(chat_id, image_paths or [], file_paths or [])

        thread = threading.Thread(
            target=self._execute_prompt,
            args=(chat_id, text, staged_images, staged_files),
            daemon=True,
        )
        thread.start()

    def _execute_prompt(self, chat_id: int, prompt: str, staged_images: List[Path], staged_files: List[Path]):
        state = self._get_chat_state(chat_id)
        prompt_text = self._build_prompt(prompt, staged_files)
        if not prompt_text.strip():
            # Image-only Telegram messages still need a non-empty stdin prompt.
            prompt_text = "请查看附带的图片或文件，并根据其中内容继续处理。"
        preview = prompt.strip().replace("\n", " ")[:80] or "(空提示词)"
        output_file = tempfile.NamedTemporaryFile(prefix="codex_last_", suffix=".txt", delete=False).name

        command = self._build_exec_args(state, staged_images, output_file)
        job = JobState(
            chat_id=chat_id,
            prompt_preview=preview,
            started_at=time.time(),
            cwd=self.cwd,
            model=state.model,
            attachments=[str(p) for p in staged_images + staged_files],
            output_file=output_file,
        )

        status_lines = [
            "⏳ CLI 任务已启动。",
            f"📂 目录: {self.cwd}",
            f"🤖 模型: {state.model or '默认'}",
            f"🔁 会话: {state.current_session_id or '新建'}",
            f"⚙️ 模式: {self.exec_mode}",
        ]
        if staged_images:
            status_lines.append(f"🖼️ 图片: {len(staged_images)}")
        if staged_files:
            status_lines.append(f"📎 文件: {len(staged_files)}")
        self.send_telegram(chat_id, "\n".join(status_lines))

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=os.path.expanduser("~"),
                env={**os.environ, "TERM": "dumb", "NO_COLOR": "1"},
            )
            if process.stdin is not None:
                process.stdin.write(prompt_text)
                process.stdin.close()
            job.process = process
            with self.lock:
                self.active_job = job
                self.current_process = process

            heartbeat_thread = threading.Thread(target=self._heartbeat_loop, args=(job,), daemon=True)
            heartbeat_thread.start()

            assert process.stdout is not None
            for line in process.stdout:
                clean = line.strip()
                if not clean:
                    continue
                self._handle_event(job, clean, state)

            process.wait()
            job.return_code = process.returncode

            final_text = self._read_last_message(job.output_file) or job.last_agent_message
            if final_text:
                for chunk in self._split_message(final_text, 4000):
                    self.send_telegram(chat_id, chunk)
            elif job.raw_lines:
                raw_tail = "\n".join(job.raw_lines[-20:])
                self.send_telegram(chat_id, raw_tail)

            if job.return_code not in (0, None):
                if job.raw_lines:
                    raw_tail = "\n".join(job.raw_lines[-20:])
                    self.send_telegram(chat_id, f"⚠️ CLI 失败输出:\n{raw_tail[:3500]}")
                self.send_telegram(chat_id, f"⚠️ CLI 进程已退出，返回码: {job.return_code}")
        except Exception as e:
            logger.error("CLI exec error: %s", e)
            self.send_telegram(chat_id, f"❌ 执行出错: {e}")
        finally:
            job.completed = True
            with self.lock:
                self.current_process = None
                self.active_job = None
            try:
                if job.output_file and os.path.exists(job.output_file):
                    os.remove(job.output_file)
            except OSError:
                pass

    def _build_exec_args(
        self,
        state: ChatState,
        image_paths: List[Path],
        output_file: str,
    ) -> List[str]:
        command = list(self.base_command)
        if state.current_session_id:
            command.extend(["exec", "-C", self.cwd, "resume", "--json", "--output-last-message", output_file])
        else:
            command.extend(["exec", "--json", "--output-last-message", output_file, "--skip-git-repo-check", "-C", self.cwd])

        if self.exec_mode == "YOLO":
            command.append("--dangerously-bypass-approvals-and-sandbox")
        elif self.exec_mode == "FULL_AUTO":
            command.append("--full-auto")
        else:
            command.extend(["-a", "never", "-s", "workspace-write"])

        if state.model:
            command.extend(["--model", state.model])

        for image_path in image_paths:
            command.extend(["--image", str(image_path)])

        if state.current_session_id:
            # Use stdin for the prompt so `--image` cannot consume it as a variadic arg.
            command.extend(["--", state.current_session_id, "-"])
        else:
            command.extend(["--", "-"])

        return command

    def _heartbeat_loop(self, job: JobState):
        while not job.completed:
            time.sleep(self.heartbeat_seconds)
            if job.completed:
                break
            elapsed = int(time.time() - job.started_at)
            lines = [
                f"💓 CLI 仍在处理中 ({elapsed}s)",
                f"📍 阶段: {job.status}",
            ]
            if job.detail:
                lines.append(f"📝 详情: {job.detail}")
            if job.session_id:
                lines.append(f"🔗 会话: {job.session_id[:8]}")
            self.send_telegram(job.chat_id, "\n".join(lines))

    def _handle_event(self, job: JobState, line: str, state: ChatState):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            job.raw_lines.append(line)
            return

        event_type = event.get("type", "")
        logger.info("CLI event: %s", event)

        if event_type == "thread.started":
            job.session_id = event.get("thread_id")
            state.current_session_id = job.session_id
            state.current_session_cwd = self.cwd
            job.status = "会话已建立"
            job.detail = job.session_id or ""
            return

        if event_type == "turn.started":
            job.status = "Codex 正在分析请求"
            job.detail = job.prompt_preview
            return

        if event_type == "item.started":
            item = event.get("item", {})
            item_type = item.get("type")
            if item_type == "command_execution":
                job.status = "正在执行命令"
                job.detail = self._shorten(item.get("command", ""))
            else:
                job.status = f"处理中: {item_type or 'unknown'}"
                job.detail = ""
            return

        if event_type == "item.completed":
            item = event.get("item", {})
            item_type = item.get("type")
            if item_type == "agent_message":
                job.last_agent_message = item.get("text", "") or job.last_agent_message
                job.status = "正在整理回复"
                job.detail = self._shorten(job.last_agent_message.replace("\n", " "), limit=100)
            elif item_type == "command_execution":
                exit_code = item.get("exit_code")
                job.status = "命令执行完成"
                job.detail = self._shorten(item.get("command", ""))
                if exit_code not in (0, None):
                    job.detail = f"{job.detail} (exit={exit_code})"
            return

        if event_type == "turn.completed":
            usage = event.get("usage", {})
            job.status = "已完成"
            if usage:
                job.detail = (
                    f"tokens in={usage.get('input_tokens', 0)} "
                    f"out={usage.get('output_tokens', 0)}"
                )

    def _stage_uploads(
        self,
        chat_id: int,
        image_paths: List[str],
        file_paths: List[str],
    ) -> Tuple[List[Path], List[Path]]:
        upload_root = Path(self.cwd) / ".antigravity-bridge" / "uploads" / str(chat_id)
        upload_root.mkdir(parents=True, exist_ok=True)

        staged_images: List[Path] = []
        staged_files: List[Path] = []
        timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")

        for idx, src in enumerate(image_paths + file_paths):
            source = Path(src)
            if not source.exists():
                continue
            safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", source.name) or f"upload_{idx}"
            dest = upload_root / f"{timestamp}-{idx}-{safe_name}"
            try:
                shutil.copy2(source, dest)
            except Exception as e:
                logger.error("Failed to stage upload %s: %s", source, e)
                continue
            if dest.suffix.lower() in IMAGE_EXTENSIONS and self._is_valid_image(dest):
                staged_images.append(dest)
            else:
                staged_files.append(dest)

        return staged_images, staged_files

    def _is_valid_image(self, path: Path) -> bool:
        try:
            with Image.open(path) as img:
                img.verify()
            return True
        except (OSError, UnidentifiedImageError) as e:
            logger.warning("Invalid image upload %s: %s", path, e)
            return False

    def _build_prompt(self, user_prompt: str, staged_files: List[Path]) -> str:
        prompt = self._expand_at_files(user_prompt)
        attachment_sections = []

        if staged_files:
            lines = [
                "Telegram 上传的文件已经保存到当前工作区，可直接读取：",
            ]
            for path in staged_files:
                rel_path = os.path.relpath(path, self.cwd)
                lines.append(f"- {rel_path}")

                suffix = path.suffix.lower()
                if suffix in TEXT_EXTENSIONS:
                    try:
                        if path.stat().st_size <= MAX_INLINE_FILE_BYTES:
                            content = path.read_text(encoding="utf-8", errors="replace")
                            lines.append(f"文件内容 {rel_path}:")
                            lines.append(f"```text\n{content}\n```")
                    except Exception as e:
                        logger.error("Failed to inline staged file %s: %s", path, e)
            attachment_sections.append("\n".join(lines))

        if attachment_sections:
            prompt = f"{prompt}\n\n" + "\n\n".join(attachment_sections)

        return prompt.strip()

    def _expand_at_files(self, prompt: str) -> str:
        def repl(match: re.Match) -> str:
            token = match.group(1)
            candidate = Path(token)
            if not candidate.is_absolute():
                candidate = Path(self.cwd) / token
            candidate = candidate.resolve()

            try:
                candidate.relative_to(Path(self.cwd).resolve())
            except ValueError:
                return f"[引用文件超出工作目录，忽略: @{token}]"

            if not candidate.exists():
                return f"[未找到文件: @{token}]"

            if candidate.is_dir():
                return f"[目录引用: {candidate.relative_to(self.cwd)}]"

            if candidate.suffix.lower() not in TEXT_EXTENSIONS:
                return f"[文件可读取: {candidate.relative_to(self.cwd)}]"

            try:
                raw = candidate.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                return f"[读取文件失败: {candidate.relative_to(self.cwd)}: {e}]"

            if len(raw.encode("utf-8")) > MAX_INLINE_FILE_BYTES:
                raw = raw[:MAX_INLINE_FILE_BYTES] + "\n...[truncated]"

            rel_path = candidate.relative_to(self.cwd)
            return f"[文件 {rel_path} 内容]\n```text\n{raw}\n```"

        return re.sub(r"(?<!\S)@([^\s]+)", repl, prompt)

    def _read_last_message(self, output_file: Optional[str]) -> str:
        if not output_file or not os.path.exists(output_file):
            return ""
        try:
            with open(output_file, "r", encoding="utf-8", errors="replace") as f:
                return f.read().strip()
        except Exception as e:
            logger.error("Failed reading output_last_message file %s: %s", output_file, e)
            return ""

    def _get_current_account_info(self) -> Optional[dict]:
        if not self.AUTH_JSON_FILE.exists():
            return None
        try:
            raw_auth = self.AUTH_JSON_FILE.read_text(encoding="utf-8")
            auth = json.loads(raw_auth)
        except Exception as e:
            logger.warning("Failed to read auth.json: %s", e)
            return None

        tokens = auth.get("tokens") or {}
        payload = self._decode_jwt_payload(tokens.get("id_token"))
        if not payload:
            return None

        auth_info = payload.get("https://api.openai.com/auth") or {}
        return {
            "email": payload.get("email") or "unknown",
            "plan": auth_info.get("chatgpt_plan_type") or "unknown",
            "account_id": tokens.get("account_id") or auth_info.get("chatgpt_account_id") or "unknown",
            "auth_json": raw_auth,
        }

    def _decode_jwt_payload(self, token: Optional[str]) -> Optional[dict]:
        if not token:
            return None
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload = parts[1]
        padding = "=" * (-len(payload) % 4)
        try:
            decoded = base64.urlsafe_b64decode(payload + padding).decode("utf-8")
            return json.loads(decoded)
        except Exception as e:
            logger.warning("Failed to decode JWT payload: %s", e)
            return None

    def _get_best_quota(self) -> Tuple[Optional[dict], str]:
        live_quota = self._get_live_rate_limits()
        if live_quota:
            return live_quota, "实时 (Codex /status)"
        return None, ""

    def _get_live_rate_limits(self) -> Optional[dict]:
        master_fd = None
        slave_fd = None
        process = None
        try:
            master_fd, slave_fd = pty.openpty()
            process = subprocess.Popen(
                self.base_command,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=os.path.expanduser("~"),
                env={**os.environ, "TERM": "xterm-256color"},
                text=False,
            )
            os.close(slave_fd)
            slave_fd = None
        except Exception as e:
            logger.warning("Failed to start Codex PTY for quota query: %s", e)
            try:
                if slave_fd is not None:
                    os.close(slave_fd)
            except Exception:
                pass
            try:
                if master_fd is not None:
                    os.close(master_fd)
            except Exception:
                pass
            return None

        output = ""
        deadline = time.time() + 20
        status_sent = False
        quit_sent = False

        try:
            while time.time() < deadline:
                now = time.time()
                if not status_sent and now >= deadline - 17:
                    os.write(master_fd, b"/status\r")
                    status_sent = True
                if not quit_sent and now >= deadline - 2:
                    os.write(master_fd, b"/quit\r")
                    quit_sent = True

                ready, _, _ = select.select([master_fd], [], [], 0.2)
                if ready:
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output += chunk.decode("utf-8", errors="replace")
                    if self._has_complete_realtime_quota_output(output):
                        parsed = self._parse_status_output(output)
                        if parsed:
                            return parsed

                if process.poll() is not None:
                    break

            return self._parse_status_output(output)
        finally:
            try:
                if process is not None:
                    process.kill()
            except Exception:
                pass
            try:
                if process is not None:
                    process.wait(timeout=1)
            except Exception:
                pass
            try:
                if master_fd is not None:
                    os.close(master_fd)
            except Exception:
                pass

    def _get_latest_rate_limits(self) -> Optional[dict]:
        files = list(self.SESSIONS_DIR.rglob("rollout-*.jsonl"))
        if not files:
            return None

        def mtime(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0

        for path in sorted(files, key=mtime, reverse=True)[:20]:
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue

            for raw in reversed(lines):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                payload = entry.get("payload") or {}
                rate_limits = payload.get("rate_limits") or {}
                primary = rate_limits.get("primary") or {}
                secondary = rate_limits.get("secondary") or {}
                if entry.get("type") == "event_msg" and payload.get("type") == "token_count" and primary:
                    return {
                        "used5h": int(primary.get("used_percent") or 0),
                        "reset5h": int(primary.get("resets_at") or 0),
                        "usedWeekly": int(secondary.get("used_percent") or 0),
                        "resetWeekly": int(secondary.get("resets_at") or 0),
                        "planType": rate_limits.get("plan_type") or "unknown",
                        "timestamp": entry.get("timestamp") or "",
                    }
        return None

    def _parse_status_output(self, raw: str) -> Optional[dict]:
        clean = self._strip_ansi(raw)
        lines = [line.replace("\r", "") for line in clean.splitlines()]
        five_h_match = re.search(
            r"5h\s+limit:[^\n]*?(\d+)%\s+left(?:[^\n]*?resets?\s+(\d{1,2}):(\d{2}))?",
            clean,
            flags=re.IGNORECASE,
        )
        weekly_line = ""
        weekly_reset_line = ""
        for idx, line in enumerate(lines):
            if re.search(r"weekly\s+limit:", line, flags=re.IGNORECASE):
                weekly_line = line
                if idx + 1 < len(lines):
                    weekly_reset_line = lines[idx + 1]
                break
        weekly_left_match = re.search(r"weekly\s+limit:[^\n]*?(\d+)%\s+left", weekly_line, flags=re.IGNORECASE)
        weekly_reset_match = re.search(r"resets?\s+(\d{1,2}):(\d{2})\s+on\s+(\d{1,2})\s+(\w+)", weekly_reset_line, flags=re.IGNORECASE)
        if not five_h_match and not weekly_left_match:
            return None

        remaining_5h = int(five_h_match.group(1)) if five_h_match else 100
        remaining_weekly = int(weekly_left_match.group(1)) if weekly_left_match else 100

        plan_match = re.search(r"Account:\s+\S+\s+\((\w+)\)", clean, flags=re.IGNORECASE)
        plan_type = plan_match.group(1).lower() if plan_match else "unknown"

        return {
            "used5h": 100 - remaining_5h,
            "reset5h": self._parse_same_day_reset_time(five_h_match.group(2), five_h_match.group(3)) if five_h_match and five_h_match.group(2) and five_h_match.group(3) else 0,
            "usedWeekly": 100 - remaining_weekly,
            "resetWeekly": self._parse_dated_reset_time(
                weekly_reset_match.group(1),
                weekly_reset_match.group(2),
                weekly_reset_match.group(3),
                weekly_reset_match.group(4),
            ) if weekly_reset_match else 0,
            "planType": plan_type,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def _has_complete_realtime_quota_output(self, raw: str) -> bool:
        clean = self._strip_ansi(raw)
        if not re.search(r"5h\s+limit:[^\n]*\d+%\s+left[^\n]*resets?\s+\d{1,2}:\d{2}", clean, flags=re.IGNORECASE):
            return False
        lines = [line.replace("\r", "") for line in clean.splitlines()]
        for idx, line in enumerate(lines):
            if re.search(r"weekly\s+limit:[^\n]*\d+%\s+left", line, flags=re.IGNORECASE):
                next_line = lines[idx + 1] if idx + 1 < len(lines) else ""
                if re.search(r"resets?\s+\d{1,2}:\d{2}\s+on\s+\d{1,2}\s+\w+", next_line, flags=re.IGNORECASE):
                    return True
        return False

    def _parse_same_day_reset_time(self, hh: str, mm: str) -> int:
        now = datetime.now()
        try:
            reset_dt = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        except ValueError:
            return 0
        if reset_dt.timestamp() <= time.time():
            reset_dt = reset_dt.replace(day=reset_dt.day) + timedelta(days=1)
        return int(reset_dt.timestamp())

    def _parse_dated_reset_time(self, hh: str, mm: str, dd: str, mon: str) -> int:
        months = {
            "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        }
        now = datetime.now()
        month_num = months.get(mon[:3].lower(), now.month)
        try:
            reset_dt = datetime(now.year, month_num, int(dd), int(hh), int(mm))
        except ValueError:
            return 0
        if reset_dt.timestamp() < time.time() - 86400:
            reset_dt = reset_dt.replace(year=now.year + 1)
        return int(reset_dt.timestamp())

    def _strip_ansi(self, text: str) -> str:
        return re.sub(r"\x1B(?:\[[0-9;]*[a-zA-Z]|\][^\x07]*\x07|\[[\?]?[0-9;]*[hlJKmsu])", "", text)

    def _format_timestamp(self, unix_ts: int) -> str:
        if not unix_ts:
            return "N/A"
        return datetime.fromtimestamp(unix_ts).strftime("%Y-%m-%d %H:%M:%S")

    def _format_relative_time(self, unix_ts: int) -> str:
        if not unix_ts:
            return "N/A"
        diff = int(unix_ts - time.time())
        if diff <= 0:
            return "已重置"
        hours = diff // 3600
        minutes = (diff % 3600) // 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def _sync_codex_quota_to_cloud(self, account: Optional[dict], quota: dict) -> Optional[str]:
        if not account:
            return "☁️ 云端同步: 跳过，未读取到当前账号信息。"
        if not self.cloud_api_base or not self.cloud_api_key:
            return "☁️ 云端同步: 跳过，未配置 API 地址或密钥。"

        payload = {
            "email": account.get("email"),
            "plan": account.get("plan"),
            "status": "available",
            "auth_json": account.get("auth_json"),
            "used_5h": int(quota.get("used5h") or 0),
            "reset_5h": int(quota.get("reset5h") or 0),
            "used_weekly": int(quota.get("usedWeekly") or 0),
            "reset_weekly": int(quota.get("resetWeekly") or 0),
        }

        try:
            accounts = self._cloud_list_accounts()
            exists = any((item.get("email") or "").lower() == (account.get("email") or "").lower() for item in accounts)
            self._cloud_report_codex_status(payload)
            if exists:
                return "☁️ 云端同步: 已上报当前账号配额。"
            return "☁️ 云端同步: 云端不存在该账号，已自动添加并上报配额。"
        except Exception as e:
            logger.warning("Failed syncing Codex quota to cloud: %s", e)
            return f"☁️ 云端同步失败: {e}"

    def _cloud_list_accounts(self) -> List[dict]:
        data = self._cloud_api_request("/api/codex/accounts", method="GET")
        accounts = data.get("accounts")
        return accounts if isinstance(accounts, list) else []

    def _cloud_report_codex_status(self, payload: dict) -> None:
        self._cloud_api_request("/api/codex/report_status", method="POST", body=payload)

    def _cloud_api_request(self, path: str, method: str = "GET", body: Optional[dict] = None) -> dict:
        url = f"{self.cloud_api_base}{path}"
        data = None
        headers = {
            "Authorization": f"Bearer {self.cloud_api_key}",
            "Content-Type": "application/json",
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")

        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace").strip()
            if e.code == 401:
                raise RuntimeError("Unauthorized: invalid cloud API key")
            raise RuntimeError(f"HTTP {e.code}: {detail or e.reason}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"network error: {e.reason}")

        if not raw.strip():
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"invalid cloud response: {e}")

    def _lookup_session_cwd(self, session_id: str) -> Optional[str]:
        if not session_id or not self.SESSIONS_DIR.exists():
            return None

        pattern = f"*{session_id}.jsonl"
        try:
            for path in self.SESSIONS_DIR.rglob(pattern):
                try:
                    with path.open("r", encoding="utf-8", errors="replace") as f:
                        first_line = f.readline().strip()
                    if not first_line:
                        continue
                    item = json.loads(first_line)
                    payload = item.get("payload", {})
                    if payload.get("id") == session_id:
                        return payload.get("cwd")
                except Exception as e:
                    logger.error("Failed reading session metadata %s: %s", path, e)
        except Exception as e:
            logger.error("Failed searching session metadata for %s: %s", session_id, e)
        return None

    def _resolve_workspace_path(self, path: str) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = Path(self.cwd) / candidate
        candidate = candidate.resolve()
        cwd_root = Path(self.cwd).resolve()
        try:
            candidate.relative_to(cwd_root)
        except ValueError:
            raise ValueError(f"路径超出当前工作目录: {candidate}")
        return candidate

    def _list_child_repos(self, target: Path) -> List[Path]:
        return [item for item in self._visible_entries(target, keep_dot_git_children=True) if item.is_dir() and (item / ".git").exists()]

    def _visible_entries(self, target: Path, keep_dot_git_children: bool = False) -> List[Path]:
        try:
            entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except Exception:
            return []
        visible: List[Path] = []
        for item in entries:
            if item.name in NOISY_PATH_NAMES or item.name.startswith(NOISY_PATH_PREFIXES):
                if keep_dot_git_children and item.name == ".git":
                    visible.append(item)
                continue
            visible.append(item)
        return visible

    def _suggest_workspace_paths(self, raw_path: str, files_only: bool = False, limit: int = 8) -> List[str]:
        needle = Path(raw_path).name.lower()
        if not needle:
            return []

        root = Path(self.cwd).resolve()
        matches: List[str] = []
        try:
            for path in root.rglob("*"):
                if len(matches) >= limit:
                    break
                if files_only and not path.is_file():
                    continue
                if needle not in path.name.lower():
                    continue
                try:
                    rel = str(path.relative_to(root))
                except Exception:
                    rel = str(path)
                matches.append(rel)
        except Exception:
            return []
        return matches

    def _shorten(self, text: str, limit: int = 120) -> str:
        text = text.strip()
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def _truncate_block(self, text: str, header: Optional[str] = None, max_chars: int = 3500) -> str:
        body = text
        truncated = False
        if len(body) > max_chars:
            body = body[:max_chars] + "\n...[truncated]"
            truncated = True
        prefix = f"{header}\n\n" if header else ""
        suffix = "\n\nℹ️ 输出已截断。" if truncated else ""
        return f"{prefix}```text\n{body}\n```{suffix}"

    def _code_block_html(self, text: str, header: Optional[str] = None, truncated: bool = False) -> str:
        prefix = f"{header}\n\n" if header else ""
        suffix = "\n\nℹ️ 输出已截断。" if truncated else ""
        return f"{prefix}<pre><code>{html.escape(text)}</code></pre>{suffix}"

    def _truncate_block_html(self, text: str, header: Optional[str] = None, max_chars: int = 3200) -> str:
        body = text
        truncated = False
        if len(body) > max_chars:
            body = body[:max_chars] + "\n...[truncated]"
            truncated = True
        return self._code_block_html(body, header=header, truncated=truncated)

    def _format_search_lines(self, lines: List[str], target: Path) -> List[str]:
        formatted = []
        for line in lines:
            parts = line.split(":", 2)
            if len(parts) < 3:
                formatted.append(self._shorten(line, limit=140))
                continue

            raw_path, line_no, content = parts
            path_obj = Path(raw_path)
            try:
                rel_path = path_obj.resolve().relative_to(Path(self.cwd).resolve())
            except Exception:
                try:
                    rel_path = path_obj.resolve().relative_to(target.resolve())
                except Exception:
                    rel_path = path_obj

            compact = f"{rel_path}:{line_no}: {content.strip()}"
            formatted.append(self._shorten(compact, limit=140))
        return formatted

    def _split_message(self, text: str, max_len: int = 4000) -> List[str]:
        if len(text) <= max_len:
            return [text]

        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
            split_pos = text.rfind("\n", 0, max_len)
            if split_pos == -1:
                split_pos = max_len
            chunks.append(text[:split_pos])
            text = text[split_pos:].lstrip("\n")
        return chunks

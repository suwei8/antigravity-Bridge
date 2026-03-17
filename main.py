#!/usr/bin/env python3
"""
Antigravity-Bridge Main Application

A Telegram Bot that bridges messages to a GUI application using automation,
with MCP (Model Context Protocol) server support for AI agent integration.

Compatible with Ubuntu 20.04 LTS (aarch64) and XFCE desktop environment.
"""

# CRITICAL: Save original stdout for MCP BEFORE any imports
# Some third-party libraries print to stdout during import, which corrupts MCP communication
import sys
_original_stdout = sys.stdout  # Save for MCP use
sys.stdout = sys.stderr  # Redirect stdout to stderr to prevent pollution

import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None
from telegram import Bot, Message, Update
from telegram.utils.helpers import escape_markdown
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    Filters,
    MessageHandler,
    Updater,
)

from automation.gui_automation import (
    backup_templates,
    full_workflow,
    full_workflow_media_group,
)
from automation.cli_automation import CLIBridge
from mcp.server import MCPServer


# Configure logging to file (stdout reserved for MCP)
log_file = '/tmp/gravity_main_debug.log'
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stderr),
    ]
    ,
    force=True,
)
logger = logging.getLogger(__name__)


@dataclass
class MessageBuffer:
    """Aggregates messages for a specific chat."""
    messages: List[Message] = field(default_factory=list)
    timer: Optional[threading.Timer] = None


class AntigravityBridge:
    """Main application class for Antigravity-Bridge."""
    
    def __init__(self):
        self.buffer_map: Dict[int, MessageBuffer] = defaultdict(MessageBuffer)
        self.buffer_lock = threading.Lock()
        self.bot: Optional[Bot] = None
        self.templates_dir: str = ""
        self.mcp_server: Optional[MCPServer] = None  # MCP Server 引用，用于设置 last_chat_id
        self.ALLOWED_CHAT_IDS: list = []  # 从 .env 读取
        
        self.current_mode = "GUI"
        self.cli_bridge: Optional[CLIBridge] = None
        self._shutting_down = False
        
    def setup(self) -> bool:
        """Initialize the application."""
        # 优先从环境变量读取（MCP mcp_config.json 会自动注入）
        # 如果环境变量不存在，才尝试从 .env 文件加载（兼容 daemon 模式）
        if not os.getenv('TELEGRAM_BOT_TOKEN') and load_dotenv:
            load_dotenv()
        
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not token:
            logger.error("TELEGRAM_BOT_TOKEN not set")
            return False
        
        # 从环境变量读取 TELEGRAM_CHAT_ID，支持逗号分隔多个 ID
        chat_id_str = os.getenv('TELEGRAM_CHAT_ID', '')
        if chat_id_str:
            self.ALLOWED_CHAT_IDS = [int(cid.strip()) for cid in chat_id_str.split(',') if cid.strip()]
            logger.info(f"Allowed chat IDs: {self.ALLOWED_CHAT_IDS}")
        else:
            logger.warning("TELEGRAM_CHAT_ID not set, no chat IDs allowed")
        
        # Determine templates directory
        # PyInstaller: sys._MEIPASS | Dev: script_dir
        if hasattr(sys, '_MEIPASS'):
            self.templates_dir = os.path.join(sys._MEIPASS, "templates")
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            self.templates_dir = os.path.join(script_dir, "templates")
        
        logger.info(f"Started. Script: {__file__}, TemplatesDir: {self.templates_dir}, "
                   f"DISPLAY: {os.getenv('DISPLAY', 'not set')}")
        
        # PyInstaller 二进制模式下，将模板备份到持久化目录
        # 防止 _MEI* 临时目录被系统清理或多实例竞争时丢失
        if hasattr(sys, '_MEIPASS'):
            backup_templates(self.templates_dir)
        # Initialize Telegram bot
        self.updater = Updater(token=token, use_context=True)
        self.bot = self.updater.bot
        
        # Initialize CLI Bridge
        self.current_mode = os.getenv("DEFAULT_MODE", "GUI").upper()
        if self.current_mode not in ("GUI", "CLI"):
            self.current_mode = "GUI"
            
        cli_command = os.getenv("CLI_COMMAND", "codex")
        
        def send_telegram_to_chat(chat_id: int, text: str):
            if chat_id:
                try:
                    self.bot.send_message(chat_id=chat_id, text=f"💻 [CLI] \n{text}")
                except Exception as e:
                    logger.error(f"Failed to send CLI message to Telegram: {e}")
            else:
                logger.error("No chat_id available to send CLI message.")
                
        self.cli_bridge = CLIBridge(command=cli_command, send_telegram_callback=send_telegram_to_chat)
        if self.current_mode == "CLI":
            self.cli_bridge.start()
        
        # Register handlers
        dp = self.updater.dispatcher
        
        # 命令处理器
        dp.add_handler(CommandHandler('start', self.handle_help_command))
        dp.add_handler(CommandHandler('help', self.handle_help_command))
        dp.add_handler(CommandHandler('screen', self.handle_screen_command))
        dp.add_handler(CommandHandler('mode', self.handle_mode_command))
        dp.add_handler(CommandHandler('cd', self.handle_cd_command))
        dp.add_handler(CommandHandler('status', self.handle_status_command))
        dp.add_handler(CommandHandler('cancel', self.handle_cancel_command))
        dp.add_handler(CommandHandler('exit', self.handle_exit_command))
        dp.add_handler(CommandHandler('sessions', self.handle_sessions_command))
        dp.add_handler(CommandHandler('resume', self.handle_resume_command))
        dp.add_handler(CommandHandler('last', self.handle_last_command))
        dp.add_handler(CommandHandler('new', self.handle_new_command))
        dp.add_handler(CommandHandler('session', self.handle_session_command))
        dp.add_handler(CommandHandler('save', self.handle_save_command))
        dp.add_handler(CommandHandler('pwd', self.handle_pwd_command))
        dp.add_handler(CommandHandler('files', self.handle_files_command))
        dp.add_handler(CommandHandler('ls', self.handle_ls_command))
        dp.add_handler(CommandHandler('cat', self.handle_cat_command))
        dp.add_handler(CommandHandler('repeat', self.handle_repeat_command))
        dp.add_handler(CommandHandler('search', self.handle_search_command))
        dp.add_handler(CommandHandler('tail', self.handle_tail_command))
        dp.add_handler(CommandHandler('run', self.handle_run_command))
        dp.add_handler(CommandHandler('diff', self.handle_diff_command))
        dp.add_handler(CommandHandler('tree', self.handle_tree_command))
        dp.add_handler(CommandHandler('open', self.handle_open_command))
        dp.add_handler(CommandHandler('gitstatus', self.handle_gitstatus_command))
        dp.add_handler(CommandHandler('history', self.handle_history_command))
        dp.add_handler(CommandHandler('model', self.handle_model_command))
        
        # 消息处理器
        dp.add_handler(MessageHandler(
            Filters.text | Filters.photo | Filters.document,
            self.handle_message
        ))
        
        # 注册 Bot 命令菜单（让 Telegram 客户端显示命令提示）
        try:
            from telegram import BotCommand
            commands = [
                BotCommand("help", "📖 帮助说明"),
                BotCommand("mode", "🔄 切换模式 (gui/cli)"),
                BotCommand("cd", "📂 切换 CLI 工作目录"),
                BotCommand("status", "📊 查看 CLI 状态"),
                BotCommand("cancel", "🛑 终止当前 CLI 任务"),
                BotCommand("exit", "🛑 退出当前任务"),
                BotCommand("sessions", "🗂️ 查看最近会话"),
                BotCommand("resume", "🔁 绑定会话继续"),
                BotCommand("last", "⏮️ 绑定最近会话"),
                BotCommand("new", "🆕 发起新会话"),
                BotCommand("session", "🧠 查看当前会话"),
                BotCommand("save", "💾 查看会话保存状态"),
                BotCommand("pwd", "📂 查看当前目录"),
                BotCommand("files", "📎 查看最近上传文件"),
                BotCommand("ls", "📁 查看目录"),
                BotCommand("cat", "📄 查看文件内容"),
                BotCommand("repeat", "🔁 重复上一条提示词"),
                BotCommand("search", "🔎 搜索文本"),
                BotCommand("tail", "📜 查看文件尾部"),
                BotCommand("run", "🖥️ 运行一条命令"),
                BotCommand("diff", "🧾 查看变更"),
                BotCommand("tree", "🌳 查看目录树"),
                BotCommand("open", "📂 打开路径摘要"),
                BotCommand("gitstatus", "🌿 查看 Git 状态"),
                BotCommand("history", "🕘 查看提示词历史"),
                BotCommand("model", "🤖 设置 CLI 模型"),
                BotCommand("screen", "📸 截取屏幕"),
            ]
            self.bot.set_my_commands(commands)
            logger.info("Bot commands menu registered.")
        except Exception as e:
            logger.warning(f"Failed to set bot commands: {e}")
        
        return True

    def _send_html_message(self, chat_id: int, text: str):
        self.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    
    def handle_help_command(self, update: Update, context: CallbackContext):
        """处理 /help 和 /start 命令：显示帮助说明"""
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS:
            return
        
        cwd = self.cli_bridge.cwd if self.cli_bridge else "N/A"
        help_text = (
            "Antigravity-Bridge 帮助\n"
            "====================\n\n"
            "GUI 模式 (Antigravity IDE)\n"
            "发送文字/图片，Bridge 会自动操控桌面 IDE 进行交互。\n"
            "适用于：Antigravity IDE 自动化任务。\n\n"
            "CLI 模式 (Codex CLI)\n"
            "发送文字，Bridge 调用 Codex CLI 执行你的请求并返回结果。\n"
            "支持心跳、会话恢复、模型切换、图片输入、@文件展开。\n"
            "适用于：代码分析、修复、终端操作等开发任务。\n\n"
            "可用命令\n"
            "/help - 显示本帮助信息\n"
            "/mode - 查看当前模式\n"
            "/mode gui - 切换到 GUI 模式\n"
            "/mode cli - 切换到 CLI 模式\n"
            "/cd <路径> - 切换 CLI 工作目录\n"
            "/status - 查看 CLI 当前状态\n"
            "/cancel - 终止当前 CLI 任务\n"
            "/exit - 终止当前 CLI 任务\n"
            "/sessions - 查看最近会话\n"
            "/resume <session_id|last> - 绑定会话继续\n"
            "/last - 绑定最近会话\n"
            "/resume new - 清空当前会话绑定\n"
            "/new - 发起新的 CLI 会话\n"
            "/session - 查看当前会话\n"
            "/save - 查看当前会话保存状态\n"
            "/pwd - 查看当前目录\n"
            "/files - 查看最近上传文件\n"
            "/ls [路径] - 查看目录\n"
            "/cat <文件> - 查看文件内容\n"
            "/repeat - 重复上一条提示词\n"
            "/search <pattern> - 搜索文本\n"
            "/tail <文件> - 查看文件尾部\n"
            "/run <命令> - 运行一条 shell 命令\n"
            "/diff [路径] - 查看 Git 变更\n"
            "/tree [路径] - 查看目录树\n"
            "/open <路径> - 查看路径摘要\n"
            "/gitstatus [路径] - 查看 Git 状态\n"
            "/history - 查看最近提示词历史\n"
            "/model <name> - 设置 CLI 模型\n"
            "/model default - 恢复默认模型\n"
            "/screen - 截取并发送桌面截图\n\n"
            f"当前模式: {self.current_mode}\n"
            f"工作目录: {cwd}"
        )
        self.bot.send_message(
            chat_id=chat_id,
            text=escape_markdown(help_text, version=2),
            parse_mode="MarkdownV2"
        )
    
    def handle_screen_command(self, update: Update, context: CallbackContext):
        """处理 /screen 命令：截取屏幕并发送图片"""
        chat_id = update.effective_chat.id
        logger.info(f"Received /screen command from {chat_id}")
        
        try:
            import subprocess
            
            # 截取屏幕
            screenshot_path = '/tmp/telegram_screenshot.png'
            result = subprocess.run(
                ['scrot', screenshot_path],
                capture_output=True,
                timeout=10
            )
            
            if result.returncode == 0:
                # 发送图片到 Telegram
                with open(screenshot_path, 'rb') as photo:
                    self.bot.send_photo(
                        chat_id=chat_id,
                        photo=photo,
                        caption="📸 当前屏幕截图"
                    )
                logger.info(f"Screenshot sent to {chat_id}")
            else:
                self.bot.send_message(
                    chat_id=chat_id,
                    text="❌ 截屏失败"
                )
        except Exception as e:
            logger.error(f"Screenshot error: {e}")
            self.bot.send_message(
                chat_id=chat_id,
                text=f"❌ 截屏失败: {e}"
            )

    def handle_mode_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS:
            return
            
        args = context.args
        if not args:
            cwd_info = f"\n📂 工作目录: {self.cli_bridge.cwd}" if self.cli_bridge else ""
            self.bot.send_message(chat_id=chat_id, text=f"当前模式: {self.current_mode}{cwd_info}\n使用 /mode gui 或 /mode cli 切换。\n使用 /cd <路径> 切换工作目录。")
            return
            
        new_mode = args[0].upper()
        if new_mode == "GUI":
            self.current_mode = "GUI"
            self.bot.send_message(chat_id=chat_id, text="🔄 已切换到 Antigravity GUI 模式")
        elif new_mode == "CLI":
            self.current_mode = "CLI"
            if self.cli_bridge and not self.cli_bridge.running:
                self.cli_bridge.start()
            cwd_info = f"\n📂 工作目录: {self.cli_bridge.cwd}" if self.cli_bridge else ""
            self.bot.send_message(chat_id=chat_id, text=f"🔄 已挂载 Codex CLI 模式{cwd_info}")
        else:
            self.bot.send_message(chat_id=chat_id, text="❌ 未知模式。支持: gui, cli")
    
    def handle_cd_command(self, update: Update, context: CallbackContext):
        """处理 /cd 命令：切换 CLI 工作目录"""
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS:
            return
            
        args = context.args
        if not args:
            cwd = self.cli_bridge.cwd if self.cli_bridge else "未初始化"
            self.bot.send_message(chat_id=chat_id, text=f"📂 当前工作目录: {cwd}\n使用 /cd <路径> 切换。")
            return
        
        path = ' '.join(args)  # Support paths with spaces
        if self.cli_bridge:
            result = self.cli_bridge.set_cwd(path)
            self.bot.send_message(chat_id=chat_id, text=result)
        else:
            self.bot.send_message(chat_id=chat_id, text="❌ CLI Bridge 未初始化。")

    def handle_status_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        self.bot.send_message(chat_id=chat_id, text=self.cli_bridge.get_status(chat_id))

    def handle_cancel_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        self.bot.send_message(chat_id=chat_id, text=self.cli_bridge.cancel_active())

    def handle_exit_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        self.bot.send_message(chat_id=chat_id, text=self.cli_bridge.cancel_active())

    def handle_sessions_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        self.bot.send_message(chat_id=chat_id, text=self.cli_bridge.format_sessions(chat_id))

    def handle_new_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        self.bot.send_message(chat_id=chat_id, text=self.cli_bridge.clear_session(chat_id))

    def handle_session_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        self._send_html_message(chat_id, self.cli_bridge.get_session_info(chat_id))

    def handle_save_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        self._send_html_message(chat_id, self.cli_bridge.get_save_status(chat_id))

    def handle_pwd_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        self._send_html_message(chat_id, self.cli_bridge.get_pwd_info(chat_id))

    def handle_files_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        self._send_html_message(chat_id, self.cli_bridge.format_recent_uploads(chat_id))

    def handle_ls_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        path = " ".join(context.args).strip() if context.args else "."
        self._send_html_message(chat_id, self.cli_bridge.list_directory(path))

    def handle_cat_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        if not context.args:
            self.bot.send_message(chat_id=chat_id, text="用法: /cat <文件路径>")
            return
        path = " ".join(context.args).strip()
        self._send_html_message(chat_id, self.cli_bridge.read_file_preview(path))

    def handle_repeat_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        last_prompt = self.cli_bridge.get_last_prompt(chat_id)
        if not last_prompt:
            self.bot.send_message(chat_id=chat_id, text="ℹ️ 当前还没有可重复的上一条提示词。")
            return
        self.bot.send_message(chat_id=chat_id, text="🔁 正在重复上一条提示词。")
        self.cli_bridge.send_input(chat_id=chat_id, text=last_prompt)

    def handle_search_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        if not context.args:
            self.bot.send_message(chat_id=chat_id, text="用法: /search <pattern> [路径]")
            return
        args = context.args
        pattern = args[0]
        path = " ".join(args[1:]).strip() if len(args) > 1 else None
        self._send_html_message(chat_id, self.cli_bridge.search_in_workspace(pattern, path))

    def handle_tail_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        if not context.args:
            self.bot.send_message(chat_id=chat_id, text="用法: /tail <文件路径>")
            return
        path = " ".join(context.args).strip()
        self._send_html_message(chat_id, self.cli_bridge.tail_file(path))

    def handle_run_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        if not context.args:
            self.bot.send_message(chat_id=chat_id, text="用法: /run <shell command>")
            return
        command = " ".join(context.args).strip()
        self._send_html_message(chat_id, self.cli_bridge.run_shell_command(command))

    def handle_diff_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        path = " ".join(context.args).strip() if context.args else None
        self._send_html_message(chat_id, self.cli_bridge.diff_workspace(path))

    def handle_tree_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        path = " ".join(context.args).strip() if context.args else "."
        self._send_html_message(chat_id, self.cli_bridge.tree_directory(path))

    def handle_open_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        if not context.args:
            self.bot.send_message(chat_id=chat_id, text="用法: /open <路径>")
            return
        path = " ".join(context.args).strip()
        self._send_html_message(chat_id, self.cli_bridge.open_path_info(path))

    def handle_gitstatus_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        path = " ".join(context.args).strip() if context.args else None
        self._send_html_message(chat_id, self.cli_bridge.git_status(path))

    def handle_history_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        self._send_html_message(chat_id, self.cli_bridge.get_prompt_history(chat_id))

    def handle_resume_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return

        args = context.args
        if not args:
            self.bot.send_message(
                chat_id=chat_id,
                text="用法: /resume <session_id|last|new>\n例如: /resume last",
            )
            return

        session_ref = " ".join(args).strip()
        if session_ref.lower() == "new":
            result = self.cli_bridge.clear_session(chat_id)
        else:
            result = self.cli_bridge.resume_session(chat_id, session_ref)
        self.bot.send_message(chat_id=chat_id, text=result)

    def handle_last_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return
        self.bot.send_message(chat_id=chat_id, text=self.cli_bridge.resume_session(chat_id, "last"))

    def handle_model_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_chat.id
        if chat_id not in self.ALLOWED_CHAT_IDS or not self.cli_bridge:
            return

        args = context.args
        if not args:
            self.bot.send_message(chat_id=chat_id, text=self.cli_bridge.get_status(chat_id))
            return

        model_name = " ".join(args).strip()
        if model_name.lower() in ("default", "auto", "clear", "none"):
            model_name = ""
        result = self.cli_bridge.set_model(chat_id, model_name)
        self.bot.send_message(chat_id=chat_id, text=result)
    
    def handle_message(self, update: Update, context: CallbackContext):
        """Buffer incoming messages and process in batches."""
        # 强制打印调试信息
        try:
            logger.info(f"handle_message received update: {update}")
        except Exception as e:
            logger.error(f"Error logging update: {e}")

        if not update.message:
            return
            
        message = update.message
        chat_id = message.chat_id
        
        # 检查 chat_id 是否在白名单中
        if chat_id not in self.ALLOWED_CHAT_IDS:
            logger.warning(f"Ignored message from unauthorized chat_id: {chat_id}")
            return
        
        # 更新 MCP Server 的 last_chat_id，用于自动回复
        if self.mcp_server:
            self.mcp_server.set_last_chat_id(str(chat_id))
        
        with self.buffer_lock:
            buf = self.buffer_map[chat_id]
            buf.messages.append(message)
            
            logger.info(f"Buffered message from {chat_id}. Total: {len(buf.messages)}")
            
            # Reset/Start Timer
            if buf.timer:
                buf.timer.cancel()
            
            # Wait 4 seconds quiescence before processing (多图消息需要更长时间到达)
            buf.timer = threading.Timer(
                4.0,
                self._process_batch,
                args=(chat_id,)
            )
            buf.timer.start()
    
    def _process_batch(self, chat_id: int):
        """Process a batch of buffered messages."""
        with self.buffer_lock:
            if chat_id not in self.buffer_map:
                return
            buf = self.buffer_map.pop(chat_id)
            messages = buf.messages
        
        if not messages:
            return
            
        logger.info(f"Processing Batch for Chat {chat_id} with {len(messages)} messages")
        
        # Sort by message ID
        messages.sort(key=lambda m: m.message_id)
        
        # Collect content
        image_paths: List[str] = []  # 图片文件（png, jpg, gif 等）
        file_paths: List[str] = []   # 非图片文件（txt, pdf 等）
        text_parts: List[str] = []
        
        # 图片扩展名列表
        IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp'}
        
        for i, msg in enumerate(messages):
            # Text
            if msg.text:
                text_parts.append(msg.text)
            elif msg.caption:
                text_parts.append(msg.caption)
            
            # Media
            file_id = None
            file_ext = ".png"
            is_image = True  # 默认是图片
            
            # 调试: 打印消息类型信息
            logger.info(f"Message {i}: text={bool(msg.text)}, caption={bool(msg.caption)}, "
                       f"photo={bool(msg.photo)}, document={bool(msg.document)}")
            
            if msg.photo:
                # Photo 类型一定是图片
                file_id = msg.photo[-1].file_id
                logger.info(f"Found photo with file_id: {file_id[:20]}...")
            elif msg.document:
                file_id = msg.document.file_id
                logger.info(f"Found document with file_id: {file_id[:20]}...")
                if msg.document.file_name:
                    ext = Path(msg.document.file_name).suffix.lower()
                    if ext:
                        file_ext = ext
                        # 判断是否为图片
                        is_image = ext in IMAGE_EXTENSIONS
                        logger.info(f"Document extension: {ext}, is_image: {is_image}")
            
            if file_id:
                try:
                    # Download file
                    file = self.bot.get_file(file_id)
                    local_path = f"/tmp/tg_batch_{chat_id}_{i}{file_ext}"
                    file.download(local_path)
                    
                    if is_image:
                        image_paths.append(local_path)
                        logger.info(f"Downloaded image to: {local_path}")
                    else:
                        file_paths.append(local_path)
                        logger.info(f"Downloaded file to: {local_path}")
                except Exception as e:
                    logger.error(f"Error downloading item: {e}")
        
        full_text = "\n".join(text_parts)
        
        # 统计日志
        logger.info(f"收集完成: {len(image_paths)} 张图片, {len(file_paths)} 个文件, 文字长度={len(full_text)}")
        
        if self.current_mode == "CLI":
            if full_text or image_paths or file_paths:
                self.cli_bridge.send_input(
                    chat_id=chat_id,
                    text=full_text,
                    image_paths=image_paths,
                    file_paths=file_paths,
                )

            for path in image_paths + file_paths:
                try:
                    os.remove(path)
                except OSError:
                    pass
            return
        
        if full_text:
            content_with_context = f"From Telegram: {full_text}\n⬆️ Please always use MCP Tools: antigravity-bridge to reply to this message."
            if image_paths or file_paths:
                content_with_context = f"From Telegram: {full_text} (Group/Attachments)\n⬆️ Please always use MCP Tools: antigravity-bridge to reply to this message."
        else:
            # 如果没有文字，则不发送任何文本上下文，只处理媒体文件
            content_with_context = ""
        
        # Process in background thread
        def process():
            try:
                sender = messages[0].from_user
                
                def send_status(status: str):
                    try:
                        self.bot.send_message(chat_id=sender.id, text=status)
                    except Exception as e:
                        logger.error(f"Error sending status: {e}")
                
                # Create reply_event to stop "思考中..." when MCP sends reply
                reply_event = None
                if self.mcp_server:
                    reply_event = self.mcp_server.create_reply_event()
                
                if image_paths or file_paths:
                    full_workflow_media_group(
                        image_paths,
                        content_with_context,
                        self.templates_dir,
                        send_status,
                        file_paths=file_paths,
                        reply_event=reply_event,
                    )
                else:
                    full_workflow(
                        content_with_context,
                        self.templates_dir,
                        send_status,
                        reply_event=reply_event,
                    )
            finally:
                # Cleanup downloaded files
                for path in image_paths + file_paths:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
        
        thread = threading.Thread(target=process, daemon=True)
        thread.start()
    
    def send_telegram(self, chat_id_str: str, text: str) -> Optional[Exception]:
        """
        Send a message to Telegram.
        
        Used by MCP server to send replies.
        """
        try:
            if not self.bot:
                return Exception("Telegram Bot not initialized yet")
            chat_id = int(chat_id_str)
            # Handle escaped newlines
            safe_text = text.replace("\\n", "\n")
            self.bot.send_message(chat_id=chat_id, text=safe_text)
            return None
        except Exception as e:
            logger.error(f"Error sending to Telegram: {e}")
            return e
    
    
    def run(self):
        """Start the bot and MCP server."""
        # 优先启动 MCP Server（在单独线程中监听 stdin）
        # 这样 IDE 可以立即获取工具列表，无需等待 Telegram 初始化
        # 使用保存的原始 stdout，避免被重定向影响
        self.mcp_server = MCPServer(self.send_telegram, stdout_stream=_original_stdout)
        mcp_thread = threading.Thread(target=self.mcp_server.start, daemon=True)
        mcp_thread.start()
        logger.info("MCP Server started first, listening on stdin")
        
        # 然后初始化 Telegram Bot
        if not self.setup():
            # 即使 Telegram 初始化失败，MCP Server 仍然可以响应基本请求
            logger.error("Telegram setup failed, but MCP Server is running")
            # 保持进程存活，MCP 仍可工作（只是发送消息功能不可用）
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info("Shutting down...")
            return
        
        logger.info("Antigravity Bridge Bot & MCP Server Starting...")
        
        import stat
        is_mcp = False
        try:
            mode = os.fstat(sys.stdin.fileno()).st_mode
            if stat.S_ISFIFO(mode):
                is_mcp = True
        except Exception:
            pass

        logger.info(f"Running mode: {'MCP' if is_mcp else 'Daemon'}")
        
        if not is_mcp:
            # 使用 PID 文件确保只有一个 Daemon 实例在运行（避免 Telegram polling 冲突）
            pid_file = '/tmp/antigravity_daemon.pid'
            current_pid = os.getpid()
            try:
                if os.path.exists(pid_file):
                    with open(pid_file, 'r') as f:
                        old_pid_str = f.read().strip()
                    if old_pid_str and old_pid_str.isdigit():
                        old_pid = int(old_pid_str)
                        if old_pid != current_pid:
                            try:
                                cmdline_file = f'/proc/{old_pid}/cmdline'
                                if os.path.exists(cmdline_file):
                                    with open(cmdline_file, 'rb') as f:
                                        cmdline = f.read().decode('utf-8', errors='ignore').replace('\x00', ' ')
                                    if 'antigravity' in cmdline.lower() or 'main.py' in cmdline.lower():
                                        os.kill(old_pid, 9)
                                        logger.info(f"已清理旧的后台 Daemon 进程: PID {old_pid}")
                            except ProcessLookupError:
                                pass
                            except Exception as e:
                                logger.debug(f"检查/清理旧进程时出错: {e}")
                
                # 写入当前 PID
                with open(pid_file, 'w') as f:
                    f.write(str(current_pid))
            except Exception as e:
                logger.error(f"PID 文件处理出错: {e}")
            # Start bot in background (Service Binary w/ Polling)
            try:
                self.updater.start_polling()
            except Exception as e:
                logger.critical(f"Failed to start polling: {e}")
                if "Unauthorized" in str(e) or "InvalidToken" in str(e):
                    logger.critical("FATAL: The provided Telegram Token is invalid. Please check your .env file.")
        else:
            logger.info("Running under MCP: Disabled Telegram polling and GUI monitors to prevent conflicts.")

        # Keep main thread alive
        try:
            while True:
                if is_mcp and not mcp_thread.is_alive():
                    logger.info("MCP thread ended (IDE disconnected pipe). Shutting down main process.")
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received.")
        finally:
            self._shutdown()

    def _shutdown(self):
        if self._shutting_down:
            return
        self._shutting_down = True
        logger.info("Shutting down...")

        if hasattr(self, 'updater'):
            try:
                self.updater.stop()
            except KeyboardInterrupt:
                logger.warning("Interrupted while stopping updater; continuing shutdown.")
            except Exception as e:
                logger.error(f"Error while stopping updater: {e}")

        if hasattr(self, 'cli_bridge') and self.cli_bridge:
            try:
                self.cli_bridge.stop()
            except KeyboardInterrupt:
                logger.warning("Interrupted while stopping CLI bridge; continuing shutdown.")
            except Exception as e:
                logger.error(f"Error while stopping CLI bridge: {e}")



def main():
    """Entry point."""
    app = AntigravityBridge()
    app.run()


if __name__ == "__main__":
    main()

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
        
        # Register handlers
        dp = self.updater.dispatcher
        
        # 命令处理器
        dp.add_handler(CommandHandler('screen', self.handle_screen_command))
        
        # 消息处理器
        dp.add_handler(MessageHandler(
            Filters.text | Filters.photo | Filters.document,
            self.handle_message
        ))
        
        return True
    
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
            logger.info("Shutting down...")
            if hasattr(self, 'updater'):
                self.updater.stop()



def main():
    """Entry point."""
    app = AntigravityBridge()
    app.run()


if __name__ == "__main__":
    main()

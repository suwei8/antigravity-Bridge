#!/usr/bin/env python3
"""
Antigravity-Bridge Main Application

A Telegram Bot that bridges messages to a GUI application using automation,
with MCP (Model Context Protocol) server support for AI agent integration.

Compatible with Ubuntu 20.04 LTS (aarch64) and XFCE desktop environment.
"""

import logging
import os
import sys
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
from telegram import Bot, Message, Update
from telegram.ext import (
    CallbackContext,
    CommandHandler,
    Filters,
    MessageHandler,
    Updater,
)

from automation.gui_automation import (
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
        
    def setup(self) -> bool:
        """Initialize the application."""
        # Load .env file
        load_dotenv()
        
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not token:
            logger.error("TELEGRAM_BOT_TOKEN not set")
            return False
        
        # Determine templates directory
        # PyInstaller: sys._MEIPASS | Dev: script_dir
        if hasattr(sys, '_MEIPASS'):
            self.templates_dir = os.path.join(sys._MEIPASS, "templates")
        else:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            self.templates_dir = os.path.join(script_dir, "templates")
        
        logger.info(f"Started. Script: {__file__}, TemplatesDir: {self.templates_dir}, "
                   f"DISPLAY: {os.getenv('DISPLAY', 'not set')}")
        
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
            content_with_context = f"From Telegram [{chat_id}]: {full_text}"
            if image_paths or file_paths:
                content_with_context += " (Group/Attachments)"
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
                
                if image_paths or file_paths:
                    full_workflow_media_group(
                        image_paths,
                        content_with_context,
                        self.templates_dir,
                        send_status,
                        file_paths=file_paths  # 传递非图片文件路径
                    )
                else:
                    full_workflow(
                        content_with_context,
                        self.templates_dir,
                        send_status
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
        if not self.setup():
            sys.exit(1)
        
        # Setup MCP Server
        mcp_server = MCPServer(self.send_telegram)
        
        logger.info("Antigravity Bridge Bot & MCP Server Starting...")
        
        # Start bot in background (Service Binary w/ Polling)
        self.updater.start_polling()
        
        # Start MCP server (blocks on stdin)
        mcp_thread = threading.Thread(target=mcp_server.start, daemon=True)
        mcp_thread.start()
        
        # Keep main thread alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            self.updater.stop()


def main():
    """Entry point."""
    app = AntigravityBridge()
    app.run()


if __name__ == "__main__":
    main()

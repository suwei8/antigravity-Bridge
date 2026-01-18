# Antigravity-Bridge

Telegram Bot 桥接到 GUI 应用的自动化工具，支持 MCP (Model Context Protocol) 集成。

## 功能特性

- **Telegram Bot**：接收用户消息（文字、图片）
- **GUI 自动化**：自动将消息粘贴到目标应用并提交
- **多图消息支持**：支持最多 5 张图片 + 文字的组合消息
- **状态监控**：自动检测 Replying 状态并发送 "思考中..." 反馈
- **Accept 自动点击**：自动点击 Accept 按钮
- **MCP Server**：提供 Telegram 消息发送工具

## 系统要求

- Ubuntu 20.04 LTS (aarch64)
- Python 3.8+
- X11 桌面环境 (XFCE)
- 必要的系统包：`xdotool`, `scrot`, `xclip`

## 安装

```bash
# 安装系统依赖
sudo apt install xdotool scrot xclip python3-tk python3-dev

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装 Python 依赖
pip install -r requirements.txt
```

## 配置

创建 `.env` 文件：

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

## 使用方法

```bash
source venv/bin/activate
python main.py
```

## 项目结构

```
antigravity-Bridge/
├── main.py                 # 主程序入口
├── telegram_mcp.py         # Telegram MCP Server
├── automation/
│   ├── __init__.py
│   └── gui_automation.py   # GUI 自动化模块
├── mcp/
│   ├── __init__.py
│   └── server.py           # MCP Server 实现
├── templates/              # 模板图片
│   ├── input_box.png
│   ├── Replying.png
│   └── accept_button.png
├── requirements.txt
└── .env
```

## 公共工具函数

### `click_input_box(templates_dir)`
点击输入框

### `find_replying(templates_dir)`
检测 Replying 状态

### `click_accept_button(templates_dir)`
点击 Accept 按钮

### `set_clipboard_image(image_path)`
复制图片到剪贴板（使用 Gtk）

## MCP 工具

### `send_telegram_message`
通过 Telegram Bot 发送消息

参数：
- `text` (必填): 消息内容
- `chat_id` (可选): 目标 Chat ID

## 许可证

MIT License

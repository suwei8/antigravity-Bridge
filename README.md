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

## 二进制版本一键部署

项目提供了 `manage.sh` 脚本，用于自动从 GitHub Release 下载最新的二进制版本并进行管理。

### 1. 下载管理脚本

```bash
wget https://raw.githubusercontent.com/suwei8/antigravity-Bridge/main/manage.sh
chmod +x manage.sh
```

### 2. 功能菜单

直接运行脚本即可看到功能菜单：

```bash
./manage.sh
```

### 3. 子命令使用

- **部署/更新**: `./manage.sh deploy` (自动下载最新版本并安装依赖)
- **启动**: `./manage.sh start`
- **停止**: `./manage.sh stop`
- **重启**: `./manage.sh restart`
- **查看日志**: `./manage.sh logs`

### 4. 目录结构

部署后将在当前目录下生成：
- `antigravity-bridge`: 可执行文件
- `.env`: 配置文件
- `app.log`: 运行日志
- `app.pid`: 进程 ID 文件

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

- `chat_id` (可选): 目标 Chat ID

## MCP 集成指南

Antigravity-Bridge 本身就是一个 MCP (Model Context Protocol) Server，可以被 Claude Desktop、Cursor 等支持 MCP 的 AI 客户端调用。

### 配置方法 (以 Claude Desktop 为例)

编辑配置文件 (通常位于 `~/Library/Application Support/Claude/claude_desktop_config.json`)：

```json
{
  "mcpServers": {
    "antigravity-bridge": {
      "command": "/绝对路径/antigravity-bridge",
      "args": [],
      "env": {
        "TELEGRAM_BOT_TOKEN": "你的BotToken",
        "TELEGRAM_CHAT_ID": "你的ChatID",
        "DISPLAY": ":0"
      }
    }
  }
}
```

> **注意**：如果不使用 `env` 字段，请确保二进制文件同级目录下存在正确的 `.env` 文件，并且 MCP 客户端的工作目录正确。推荐直接在 `env` 中配置。

### 注意事项

- **互斥运行**：当作为 MCP Server 使用时（即被 AI 客户端启动），**不要**同时通过 `manage.sh start` 运行后台进程。因为两个进程同时连接 Telegram Bot 会导致冲突和消息丢失。
- **功能差异**：
  - `manage.sh start` 模式：作为独立 Bot 运行，监听消息并执行 GUI 自动化。
  - MCP 模式：既可以作为工具被 AI 调用发送消息，也可以接收消息（取决于客户端生命周期）。但通常主要用于让 AI **控制**发送消息。

## 许可证

MIT License

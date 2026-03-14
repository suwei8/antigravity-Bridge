# Antigravity-Bridge

Telegram Bot 桥接到 IDE GUI 的自动化工具，支持 MCP (Model Context Protocol) 集成，让 AI 助手通过 Telegram 与你无缝交互。

## 功能特性

### 核心功能
- **Telegram Bot** — 接收用户消息（文字、图片、文档），支持批量缓冲和分组处理
- **GUI 自动化** — 使用图像匹配（PyAutoGUI）在桌面上自动操作 IDE，包括输入文本、粘贴图片、点击按钮
- **MCP Server** — 通过 stdio 与 IDE 通信，暴露 `reply_to_telegram` 工具供 AI 助手直接回复消息
- **多图消息支持** — 支持图片 + 文字的组合消息，自动转换非 PNG 图片确保剪贴板兼容
- **文件传输** — 支持接收文档文件（txt, pdf 等），并传递给 IDE

### 后台监控
- **Retry 自动恢复** — 持续监控 IDE 网络断连时的 Retry 按钮并自动点击恢复
- **配额自动切换** — 检测 Upgrade/配额耗尽弹窗，自动切换备用 AI 模型并发送 continue 指令
- **思考中心跳** — 在 AI 回复过程中自动发送「思考中...」状态通知到 Telegram
- **Accept 自动点击** — 自动点击 IDE 中的 Accept/Accept all 按钮

### 命令支持
- `/screen` — 截取当前屏幕截图并发送到 Telegram

## 系统要求

- Ubuntu 20.04 LTS (aarch64)
- Python 3.8+
- X11 桌面环境 (XFCE)
- 必要的系统包：`xdotool`, `scrot`, `xclip`, `python3-tk`, `python3-dev`

## 二进制版本一键部署

项目提供了 `manage.sh` 脚本，用于自动从 GitHub Release 下载最新的二进制版本并进行管理。

### 1. 下载管理脚本

```bash
wget -O manage.sh https://raw.githubusercontent.com/suwei8/antigravity-Bridge/main/manage.sh
chmod +x manage.sh
```

### 2. 部署

```bash
./manage.sh deploy
```

首次部署会：
- 自动检查并安装系统依赖
- 从 GitHub Releases 下载最新二进制
- 创建 `.env` 配置文件（需要输入 Telegram Bot Token）
- 自动配置 MCP 和 GEMINI 规则

### 3. 服务管理

| 命令 | 说明 |
|------|------|
| `./manage.sh start` | 启动服务 |
| `./manage.sh stop` | 停止服务 |
| `./manage.sh restart` | 重启服务 |
| `./manage.sh update` | 更新到最新版本 |
| `./manage.sh logs` | 查看实时日志 |

### 4. 手动更新

```bash
# 杀掉正在运行的老服务
pkill -9 -f "antigravity-bridge"
sleep 2
wget -O /tmp/antigravity-bridge https://github.com/suwei8/antigravity-Bridge/releases/latest/download/antigravity-bridge
chmod +x /tmp/antigravity-bridge
mv /tmp/antigravity-bridge ./antigravity-bridge
chmod +x ./antigravity-bridge
# 重启
cd /home/sw/
./manage.sh restart
```

## 源码开发

### 安装

```bash
# 安装系统依赖
sudo apt install xdotool scrot xclip python3-tk python3-dev

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装 Python 依赖
pip install -r requirements.txt
```

### 配置

创建 `.env` 文件：

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

### 运行

```bash
source venv/bin/activate
python main.py
```

### 构建二进制

```bash
source venv/bin/activate
pyinstaller --noconfirm --onefile --name antigravity-bridge \
  --add-data "templates:templates" \
  --hidden-import PIL._tkinter_finder \
  main.py
```

## 项目结构

```
antigravity-Bridge/
├── main.py                    # 主程序入口 (Telegram Bot + MCP Server + 监控线程)
├── automation/
│   ├── __init__.py
│   └── gui_automation.py      # GUI 自动化模块 (图像匹配、点击、粘贴)
├── mcp/
│   ├── __init__.py
│   └── server.py              # MCP Server 实现 (JSON-RPC 2.0 over stdio)
├── templates/                 # 模板图片 (用于图像匹配)
│   ├── input_box.png          # 输入框
│   ├── Replying.png           # 回复中指示器
│   ├── Retry.png              # 重试按钮
│   ├── Upgrade.png            # 配额弹窗
│   ├── accept_button.png      # Accept 按钮
│   ├── accept_all.png         # Accept all 按钮
│   ├── panel-ClaudeOpus.png   # Claude 模型面板
│   ├── panel-Gemini.png       # Gemini 模型面板
│   └── ...
├── manage.sh                  # 部署管理脚本
├── requirements.txt           # Python 依赖
└── .env                       # 环境变量配置 (不纳入版本控制)
```

## 架构说明

### 运行模式

1. **Daemon 模式** (`manage.sh start`)：作为独立后台服务运行
   - 启动 Telegram Bot Polling 监听消息
   - 启动 Retry 按钮监控线程
   - 启动 Upgrade 弹窗监控线程
   - 启动 MCP Server（同进程）

2. **MCP 模式** (IDE 通过 `mcp_config.json` 启动)：
   - 仅启动 MCP Server，通过 stdin/stdout 通信
   - 禁用 Telegram Polling 和 GUI 监控（避免与 Daemon 冲突）
   - AI 助手通过 `reply_to_telegram` 工具发送消息

### MCP 工具

| 工具名 | 说明 | 参数 |
|--------|------|------|
| `reply_to_telegram` | 发送消息到 Telegram | `text` (必填)、`chat_id` (可选) |

### MCP 集成配置

编辑 MCP 配置文件：

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

> **互斥运行**：Daemon 模式和 MCP 模式不应同时连接 Telegram Bot Polling，否则会导致冲突。MCP 模式下已自动禁用 Polling。

## 许可证

MIT License

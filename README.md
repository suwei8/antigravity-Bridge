# Antigravity-Bridge

Antigravity-Bridge 是一个 Telegram Bot 桥接器，支持两条工作链路：

- `GUI` 模式：通过桌面自动化驱动本地 IDE / AI 客户端。
- `CLI` 模式：通过 Codex CLI 执行代码、终端和文件相关任务。

项目同时带有 MCP Server，方便 IDE 内的 Agent 直接把最终回复回传到 Telegram。

当前项目的主要使用场景已经转向 `CLI` 模式，目标是在不坐在电脑前时，也能通过 Telegram Bot 持续使用 Codex CLI。

## 当前状态

当前源码已经包含以下能力：

- Telegram 文本、图片、文件输入
- `CLI` 长任务心跳
- Codex 会话恢复与会话列表
- 模型切换
- `@文件` 展开读取
- Telegram 侧目录、文件、搜索、Git、shell 辅助命令
- 更适合 Telegram 阅读的 HTML 输出
- 多仓库工作目录下更友好的 `/tree`、`/cat`、`/diff`、`/gitstatus`

## 运行模式

### GUI 模式

适合桌面 AI 客户端自动化：

- 图像识别输入框、按钮和面板
- 自动点击 `Retry` / `Accept`
- 截图、图片粘贴、GUI 心跳

### CLI 模式

适合远程开发与代码任务：

- 使用 `codex exec --json`
- 支持心跳消息
- 支持 `resume` 续接本地会话
- 支持 Telegram 图片传给 Codex `--image`
- 支持 Telegram 文件落盘并内联到提示词
- 支持 `YOLO` 执行模式

## Telegram 命令

### 通用命令

- `/help`
- `/mode`
- `/mode gui`
- `/mode cli`
- `/screen`

### CLI 会话命令

- `/cd <路径>`
- `/status`
- `/cancel`
- `/exit`
- `/sessions`
- `/resume <session_id|last>`
- `/last`
- `/new`
- `/session`
- `/save`
- `/model <name>`
- `/model default`

### CLI 工作区命令

- `/pwd`
- `/files`
- `/ls [路径]`
- `/tree [路径]`
- `/open <路径>`
- `/cat <文件>`
- `/tail <文件>`
- `/search <pattern> [路径]`
- `/run <shell command>`
- `/diff [路径]`
- `/gitstatus [路径]`
- `/history`
- `/repeat`

## 环境要求

推荐正式维护、构建和发布环境：

- Oracle Cloud ARM
- `VM.Standard.A1.Flex`
- `Ubuntu 20.04.6 LTS (aarch64)`

运行兼容目标：

- Ubuntu 20.04.6 LTS (aarch64)
- Ubuntu 22.04.5 LTS (aarch64)
- Ubuntu 24.04.3 LTS (aarch64)

之所以固定在 Ubuntu 20.04 ARM 上构建，是为了避免高版本系统构建出的二进制依赖更新的 `glibc`，导致在 Ubuntu 20.04 上运行失败。

## 系统依赖

### 必要系统包

```bash
sudo apt update
sudo apt install -y \
  xdotool \
  scrot \
  xclip \
  python3-venv \
  python3-pip \
  python3-tk \
  python3-dev \
  build-essential
```

### Codex CLI

项目的 `CLI` 模式依赖本机安装 Codex CLI。

示例：

```bash
codex --version
```

## 源码开发

### 1. 创建虚拟环境

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install pyinstaller
```

### 2. 配置 `.env`

示例：

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=111111111,222222222

DEFAULT_MODE=CLI
CLI_COMMAND=/home/sw/.nvm/versions/node/v24.14.0/bin/codex
CLI_EXEC_MODE=YOLO
CLI_HEARTBEAT_SECONDS=15
CLI_CWD=/home/sw/dev_root/

DISPLAY=:10
XAUTHORITY=/home/sw/.Xauthority
```

说明：

- `DEFAULT_MODE=CLI`：默认走 Codex CLI
- `CLI_EXEC_MODE=YOLO`：尽量避免手机端审批中断
- `CLI_HEARTBEAT_SECONDS=15`：长任务心跳间隔
- `CLI_CWD`：CLI 工作根目录

### 3. 启动源码版

```bash
source venv/bin/activate
python main.py
```

前台退出：

```bash
Ctrl+C
```

### 4. 调试日志

```bash
tail -f /tmp/gravity_main_debug.log
```

## 本地构建二进制

### 关键原则

正式发布二进制只在 `Ubuntu 20.04.6 LTS ARM` 上构建。  
不要在 Ubuntu 22.04 / 24.04 上构建正式发布包，否则容易出现：

```text
GLIBC_2.35 not found
```

### 构建命令

```bash
source venv/bin/activate
pyinstaller antigravity-bridge.spec
```

构建产物：

```bash
dist/antigravity-bridge
```

### 部署到本机

无论当前机器是首次部署，还是已经存在旧版本 `/home/sw/antigravity-bridge`、`/home/sw/manage.sh`，都统一使用下面这组命令：

```bash
cd /home/sw
if [ -f manage.sh ]; then
  cp -f manage.sh manage.sh.bak.$(date +%Y%m%d-%H%M%S)
fi
curl -fsSL -o manage.sh https://raw.githubusercontent.com/suwei8/antigravity-Bridge/main/manage.sh
chmod +x manage.sh
./manage.sh deploy
./manage.sh start
```

说明：

- `manage.sh deploy` 会从 `https://github.com/suwei8/antigravity-Bridge` 的 Latest Release 下载二进制 `antigravity-bridge`
- 如果当前目录已有旧版本 `antigravity-bridge`，脚本会先备份再替换
- `./manage.sh start` 之前会读取 `.env` 并自动修正 `DISPLAY` / `XAUTHORITY`

如果你刚在本机完成 `pyinstaller` 构建，希望直接替换当前机器上的二进制，可使用：

```bash
cd /home/sw
pkill -9 -x antigravity-bridge || true
if [ -f antigravity-bridge ]; then
  cp -f antigravity-bridge antigravity-bridge.bak.$(date +%Y%m%d-%H%M%S)
fi
cp -f /home/sw/dev_root/antigravity-Bridge/dist/antigravity-bridge /home/sw/antigravity-bridge
chmod +x /home/sw/antigravity-bridge
./manage.sh start
```

### 查看部署日志

```bash
cd /home/sw
./manage.sh logs
```

## 推荐维护流程

当前推荐流程：

1. 在 Ubuntu 20.04 ARM 机器上修改源码
2. 用源码版验证 Telegram 侧功能
3. 本地 `pyinstaller` 构建二进制
4. 本机替换 `/home/sw/antigravity-bridge`
5. 再分发到其他 Ubuntu 20.04 / 22.04 / 24.04 ARM 机器

当前不再把 GitHub-hosted Actions 作为正式构建来源。

## 项目结构

```text
antigravity-Bridge/
├── main.py
├── manage.sh
├── antigravity-bridge.spec
├── automation/
│   ├── cli_automation.py
│   └── gui_automation.py
├── mcp/
│   └── server.py
├── templates/
├── requirements.txt
└── .env
```

## MCP

项目保留 MCP Server，用于 IDE / Agent 内部直接发送 Telegram 回复。

核心 MCP 工具：

- `reply_to_telegram`

## 补充文档

迁移到新 Ubuntu 20.04 ARM 环境后，优先阅读：

- [AGENT_HANDOFF_OCI20.md](/home/sw/dev_root/antigravity-Bridge/AGENT_HANDOFF_OCI20.md)

## License

MIT

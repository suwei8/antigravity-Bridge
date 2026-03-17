# Agent Handoff For OCI Ubuntu 20.04 ARM

这份文档用于新环境接手项目时快速建立上下文。目标环境是：

- Oracle Cloud ARM
- `VM.Standard.A1.Flex`
- `Ubuntu 20.04.6 LTS (aarch64)`

该环境将作为后续唯一正式构建环境。

## 一句话理解项目

这是一个 Telegram Bot 桥接器：`GUI` 模式负责桌面自动化，`CLI` 模式负责把 Telegram 消息转成 Codex CLI 任务执行，MCP 负责把 IDE / Agent 的结果再发回 Telegram。

## 为什么迁移到 Ubuntu 20.04 ARM

项目已经遇到过一次兼容性问题：

- 在 Ubuntu 22.04 ARM 上用 PyInstaller 构建的二进制
- 在 Ubuntu 20.04 ARM 上运行时报错

典型错误：

```text
GLIBC_2.35 not found
```

因此后续正式构建必须固定在 Ubuntu 20.04 ARM 上，这样产物通常可以向上兼容到 Ubuntu 22.04 / 24.04。

## 当前代码状态

当前项目已经不是早期单纯 GUI bridge，而是以 CLI bridge 为主，已经完成这些增强：

- `codex exec --json` 驱动
- 去掉硬编码 5 分钟超时
- 增加 Telegram 心跳
- 支持 `resume` 会话恢复
- 支持 `/sessions`、`/resume`、`/new`、`/session`
- 支持 `/model`
- 支持 Telegram 图片输入到 Codex `--image`
- 支持 Telegram 文件上传、落盘、内联
- 支持 `@文件` 展开
- 支持 `/pwd`、`/ls`、`/tree`、`/cat`、`/search`、`/run`、`/diff`、`/gitstatus`
- 输出改成更适合 Telegram 阅读的 HTML
- 多仓库工作目录下命令行为做过优化
- 优化了 Ctrl+C 下源码版的退出行为

## 重要文件

- [main.py](/home/sw/dev_root/antigravity-Bridge/main.py)
  入口、Telegram 命令注册、模式切换、消息分发、优雅退出

- [automation/cli_automation.py](/home/sw/dev_root/antigravity-Bridge/automation/cli_automation.py)
  Codex CLI 桥接核心逻辑、会话恢复、心跳、附件、工作区命令

- [automation/gui_automation.py](/home/sw/dev_root/antigravity-Bridge/automation/gui_automation.py)
  GUI 自动化逻辑

- [manage.sh](/home/sw/dev_root/antigravity-Bridge/manage.sh)
  部署与服务管理脚本

- [antigravity-bridge.spec](/home/sw/dev_root/antigravity-Bridge/antigravity-bridge.spec)
  PyInstaller 构建配置

## 本机维护原则

从现在开始：

1. 不依赖 GitHub-hosted Actions 产出正式二进制
2. 不依赖 GitHub Release 自动构建
3. 在 Ubuntu 20.04 ARM 本机完成：
   - 修改
   - 调试
   - 构建
   - 替换部署

GitHub 可以继续用来：

- 存源码
- 提交版本
- 可选上传 release 资产

但二进制的“正式构建动作”必须发生在 Ubuntu 20.04 ARM 上。

## 首次接手要检查的内容

### 1. 系统依赖

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

### 2. Codex CLI

确认 Codex CLI 已安装并可执行：

```bash
codex --version
```

### 3. Python 环境

```bash
cd /home/sw/dev_root/antigravity-Bridge
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install pyinstaller
```

### 4. `.env`

至少检查这些变量：

```env
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
DEFAULT_MODE=CLI
CLI_COMMAND=/home/sw/.nvm/versions/node/v24.14.0/bin/codex
CLI_EXEC_MODE=YOLO
CLI_HEARTBEAT_SECONDS=15
CLI_CWD=/home/sw/dev_root/
DISPLAY=:10
XAUTHORITY=/home/sw/.Xauthority
```

## 推荐调试流程

### 前台运行源码版

```bash
cd /home/sw/dev_root/antigravity-Bridge
source venv/bin/activate
python main.py
```

### 查看日志

```bash
tail -f /tmp/gravity_main_debug.log
```

### Telegram 验收顺序

```text
/help
/status
/tree
/sessions
hi
发送图片
发送文件
请读取 @README.md 并总结
```

## 构建和部署流程

### 1. 构建

```bash
cd /home/sw/dev_root/antigravity-Bridge
source venv/bin/activate
pyinstaller antigravity-bridge.spec
```

### 2. 替换部署二进制

```bash
pkill -9 -f "antigravity-bridge"
cp -f /home/sw/antigravity-bridge /home/sw/antigravity-bridge.bak.$(date +%Y%m%d-%H%M%S)
cp -f dist/antigravity-bridge /home/sw/antigravity-bridge
chmod +x /home/sw/antigravity-bridge
cd /home/sw
./manage.sh restart
```

### 3. 查看状态

```bash
cd /home/sw
./manage.sh logs
```

## 已知结论

### 1. 发布机构建环境必须固定

只在 Ubuntu 20.04 ARM 上构建正式版本。

### 2. Telegram CLI 体验已经重点优化

已经处理过的典型问题：

- 长任务只有“正在处理”但没有心跳
- 5 分钟硬超时导致长任务被杀
- `resume` 参数顺序错误
- 恢复会话后 cwd 漂移
- `/help` MarkdownV2 报错
- `/search` 缺少 `rg` 时直接失败
- `/tree`、`/diff`、`/gitstatus` 在多仓库根目录下体验差

### 3. 当前工作区常见结构

`CLI_CWD` 常设为：

```text
/home/sw/dev_root/
```

这意味着 `/tree`、`/ls`、`/cat README.md` 这类命令默认会站在多仓库根目录下运行。代码里已经对这个场景做了专门优化。

## 不建议做的事

- 不要在 Ubuntu 22.04 / 24.04 ARM 上构建正式发布二进制
- 不要恢复 GitHub-hosted ARM runner 作为正式发布来源
- 不要随意删除 `.codex/sessions`，否则会影响 `resume`
- 不要用 `git reset --hard` 清工作区

## 如果需要继续迭代

优先顺序建议：

1. 先用源码版调试
2. Telegram 真实验收通过后再构建
3. 构建后先在本机部署验证
4. 再分发到其他 OCI ARM 机器

## 维护目标

目标不是做一个“理论上能跑”的 Bridge，而是：

- 远程手机端可观测
- 长任务不中断
- 会话可恢复
- 工作区命令好读
- Ubuntu 20.04 / 22.04 / 24.04 ARM 兼容

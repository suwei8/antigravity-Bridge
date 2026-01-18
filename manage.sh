#!/bin/bash

# Antigravity-Bridge 管理脚本
# 功能: 部署、启动、停止、重启、查看日志

APP_NAME="antigravity-bridge"
REPO="suwei8/antigravity-Bridge"
DOWNLOAD_URL="https://github.com/${REPO}/releases/latest/download/${APP_NAME}"
LOG_FILE="app.log"
PID_FILE="app.pid"

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

info() {
    echo -e "${GREEN}[INFO] $1${NC}"
}

error() {
    echo -e "${RED}[ERROR] $1${NC}"
}

check_dependencies() {
    info "检查系统依赖..."
    local deps=("xdotool" "scrot" "xclip")
    local install_needed=0

    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &> /dev/null; then
            echo "$dep 未安装"
            install_needed=1
        fi
    done

    if [ $install_needed -eq 1 ]; then
        info "正在安装缺失的依赖 (需要 sudo 权限)..."
        sudo apt-get update
        sudo apt-get install -y xdotool scrot xclip
    else
        info "所有依赖已安装。"
    fi
}

deploy() {
    info "开始部署..."
    check_dependencies

    info "正在下载最新版本..."
    local tmp_file="${APP_NAME}.tmp"
    if curl -L -o "$tmp_file" "$DOWNLOAD_URL"; then
        chmod +x "$tmp_file"
        mv -f "$tmp_file" "$APP_NAME"
        info "下载成功并通过验证。"
        
        # 检查 .env
        if [ -f .env ]; then
            info "检测到现有 .env 配置文件"
            source .env
            token=$TELEGRAM_BOT_TOKEN
            chat_id=$TELEGRAM_CHAT_ID
        else
            echo "未检测到 .env 配置文件"
            echo "请输入您的 Telegram Bot Token:"
            read -r token
            echo "请输入您的 Chat ID:"
            read -r chat_id
            
            cat > .env << EOF
TELEGRAM_BOT_TOKEN=$token
TELEGRAM_CHAT_ID=$chat_id
EOF
            info ".env 配置文件已创建。"
        fi

        # 写入 MCP 配置
        info "正在配置 MCP..."
        MCP_CONFIG_DIR="/home/sw/.gemini/antigravity"
        MCP_CONFIG_FILE="$MCP_CONFIG_DIR/mcp_config.json"
        APP_PATH="$(pwd)/$APP_NAME"

        mkdir -p "$MCP_CONFIG_DIR"

        # 获取当前 DISPLAY，默认为 :0
        current_display="${DISPLAY:-:0}"

        cat > "$MCP_CONFIG_FILE" << EOF
{
  "mcpServers": {
    "antigravity-bridge": {
      "command": "$APP_PATH",
      "args": [],
      "env": {
        "TELEGRAM_BOT_TOKEN": "$token",
        "TELEGRAM_CHAT_ID": "$chat_id",
        "DISPLAY": "$current_display"
      }
    }
  }
}
EOF
        info "MCP 配置已写入: $MCP_CONFIG_FILE"

        # 写入 GEMINI 规则
        info "正在更新 GEMINI 规则..."
        GEMINI_CONFIG_FILE="/home/sw/.gemini/GEMINI.md"
        mkdir -p "$(dirname "$GEMINI_CONFIG_FILE")"

        cat > "$GEMINI_CONFIG_FILE" << EOF
"你在 IDE 中工作，你必须使用中文语言和用户交流，在完成用户请求的最终答复后，你必须遵守以下规则：
1. 立即调用 MCP 工具 \`antigravity-bridge\`，将完整最终答复发送到 Telegram Bot。
2. 如果内容较长，拆分为多次调用 \`antigravity-bridge\` ，优先按段落并符合Telegram阅读的代码块，确保代码块结构完整。
3.调用MCP 工具 \`antigravity-bridge\`完成回复后，禁止在IDE对话中重复输出全文，只输出一句： ok"
EOF
        info "GEMINI 规则已更新: $GEMINI_CONFIG_FILE"
        
        info "部署完成！可以使用 'bash $0 start' 启动。"
    else
        error "下载失败，请检查网络或版本是否存在。"
    fi
}

start() {
    if [ -f "$PID_FILE" ]; then
        if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
            error "程序已在运行中 (PID: $(cat $PID_FILE))"
            return
        else
            rm "$PID_FILE"
        fi
    fi

    if [ ! -f "$APP_NAME" ]; then
        error "未找到可执行文件 $APP_NAME，请先执行部署 (Option 1)"
        return
    fi
    
    # 检查 .env
    if [ ! -f .env ]; then
        error "未找到 .env 配置文件，请先创建或重新部署"
        return
    fi

    info "正在启动 $APP_NAME..."
    nohup ./$APP_NAME > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    info "启动成功! PID: $(cat $PID_FILE)"
    info "日志输出到 $LOG_FILE"
    
    # 简单的存活检查
    sleep 2
    if kill -0 $(cat "$PID_FILE") 2>/dev/null; then
        echo "运行状态: 正常"
    else
        error "启动失败，请检查日志:"
        cat "$LOG_FILE"
    fi
}

stop() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        info "正在停止程序 (PID: $pid)..."
        kill $pid 2>/dev/null
        
        # 等待进程退出
        for i in {1..5}; do
            if ! kill -0 $pid 2>/dev/null; then
                break
            fi
            sleep 1
        done
        
        if kill -0 $pid 2>/dev/null; then
            info "强制清理..."
            kill -9 $pid 2>/dev/null
        fi
        
        rm "$PID_FILE"
        info "程序已停止。"
    else
        info "程序未运行 (找不到 PID 文件)。尝试使用 pkill 清理..."
        pkill -f "./$APP_NAME"
    fi
}

restart() {
    stop
    sleep 1
    start
}

logs() {
    if [ ! -f "$LOG_FILE" ]; then
        error "日志文件不存在"
        return
    fi
    info "正在查看日志 (Ctrl+C 退出)..."
    tail -f "$LOG_FILE"
}

case "$1" in
    deploy)
        deploy
        ;;
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    logs)
        logs
        ;;
    *)
        echo "=========================================="
        echo "   Antigravity-Bridge 管理脚本"
        echo "=========================================="
        echo "1. 部署 (Deploy)"
        echo "2. 启动 (Start)"
        echo "3. 停止 (Stop)"
        echo "4. 重启 (Restart)"
        echo "5. 查看日志 (Logs)"
        echo "0. 退出 (Exit)"
        echo "=========================================="
        read -p "请输入选项 [0-5]: " choice
        
        case "$choice" in
            1) deploy ;;
            2) start ;;
            3) stop ;;
            4) restart ;;
            5) logs ;;
            0) exit 0 ;;
            *) echo "无效选项" ;;
        esac
        ;;
esac

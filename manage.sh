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
    local cmds=("xdotool" "scrot" "xclip" "gnome-screenshot")
    local pkgs=("python3-tk" "python3-dev")
    local install_needed=0

    # Check commands
    for cmd in "${cmds[@]}"; do
        if ! command -v "$cmd" &> /dev/null; then
            echo "命令 $cmd 未安装"
            install_needed=1
        fi
    done

    # Check packages (Debian/Ubuntu specific)
    for pkg in "${pkgs[@]}"; do
        if ! dpkg -s "$pkg" &> /dev/null; then
            echo "包 $pkg 未安装"
            install_needed=1
        fi
    done

    if [ $install_needed -eq 1 ]; then
        info "正在安装缺失的依赖 (需要 sudo 权限)..."
        # Combine lists for installation
        local install_list=""
        # Note: command names usually match package names for these, but not always.
        # xdotool -> xdotool, scrot -> scrot, xclip -> xclip
        for cmd in "${cmds[@]}"; do
             if ! command -v "$cmd" &> /dev/null; then
                install_list="$install_list $cmd"
             fi
        done
        for pkg in "${pkgs[@]}"; do
            if ! dpkg -s "$pkg" &> /dev/null; then
                install_list="$install_list $pkg"
            fi
        done
        
        info "安装列表: $install_list"
        sudo apt-get update
        sudo apt-get install -y $install_list
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
            # echo "请输入您的 Chat ID:"
            # read -r chat_id
            
            # 硬编码默认 Chat ID (主账号)
            chat_id="1118793113,8415850251"
            
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

        # 智能检测 DISPLAY（避免 SSH X11 forwarding 污染）
        detect_display() {
            # 1. 检查当前用户的 xRDP/Xorg 会话
            local xrdp_display=$(ps aux | grep -E "Xorg.*-config xrdp" | grep -v grep | grep "$(whoami)" | sed -n 's/.*Xorg \(:[0-9]*\).*/\1/p' | head -1)
            if [ -n "$xrdp_display" ] && [ -S "/tmp/.X11-unix/X${xrdp_display#:}" ]; then
                echo "$xrdp_display"
                return
            fi
            
            # 2. 检查 Xvfb
            local xvfb_display=$(ps aux | grep "Xvfb" | grep -v grep | sed -n 's/.*Xvfb \(:[0-9]*\).*/\1/p' | head -1)
            if [ -n "$xvfb_display" ] && [ -S "/tmp/.X11-unix/X${xvfb_display#:}" ]; then
                echo "$xvfb_display"
                return
            fi
            
            # 3. 如果 $DISPLAY 对应的 socket 存在且不像 SSH X11 forwarding（通常 >10）
            if [ -n "$DISPLAY" ]; then
                local display_num="${DISPLAY#:}"
                display_num="${display_num%%.*}"
                if [ -S "/tmp/.X11-unix/X${display_num}" ]; then
                    echo "$DISPLAY"
                    return
                fi
            fi
            
            # 4. 回退到 :0
            echo ":0"
        }
        
        current_display=$(detect_display)
        info "检测到 DISPLAY: $current_display"

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

update() {
    info "开始更新到最新版本..."
    check_dependencies

    # 获取最新版本 Tag
    info "正在获取最新版本信息..."
    local latest_tag=$(curl -sI "https://github.com/${REPO}/releases/latest" | grep -i location | awk -F/ '{print $NF}' | tr -d '\r')
    
    if [ -z "$latest_tag" ]; then
        error "无法获取最新版本号，将直接尝试下载 latest。"
        local specific_url="$DOWNLOAD_URL"
    else
        info "发现最新版本: ${GREEN}${latest_tag}${NC}"
        # 使用明确的 tag url，防止部分环境重定向出错
        local specific_url="https://github.com/${REPO}/releases/download/${latest_tag}/${APP_NAME}"
    fi

    info "正在下载最新版本..."
    local tmp_file="${APP_NAME}.tmp"
    if curl -L -o "$tmp_file" "$specific_url"; then
        # 增加文件类型的校验，防止因为网络拦截下载成了 HTML 错误页面
        if file "$tmp_file" | grep -qi "ELF"; then
            chmod +x "$tmp_file"
            
            info "正在停止当前服务..."
            stop
            
            info "替换可执行文件..."
            mv -f "$tmp_file" "$APP_NAME"
            
            info "更新成功 (${latest_tag:-latest})，正在启动服务..."
            start
        else
            error "下载的文件验证失败。内容不是可执行二进制文件，可能是网络阻断导致了 HTML 返回。"
            rm -f "$tmp_file"
        fi
    else
        error "下载请求失败，请检查网络。"
        rm -f "$tmp_file"
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
    
    if [ ! -f .env ]; then
        error "未找到 .env 配置文件，请先创建或重新部署"
        return
    fi
    
    # Load environment variables
    set -a
    source .env
    set +a

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
    update)
        update
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
        echo "6. 更新 (Update)"
        echo "0. 退出 (Exit)"
        echo "=========================================="
        read -p "请输入选项 [0-6]: " choice
        
        case "$choice" in
            1) deploy ;;
            2) start ;;
            3) stop ;;
            4) restart ;;
            5) logs ;;
            6) update ;;
            0) exit 0 ;;
            *) echo "无效选项" ;;
        esac
        ;;
esac

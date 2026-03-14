#!/bin/bash

# Antigravity-Bridge 管理脚本
# 功能: 部署、启动、停止、重启、查看日志

APP_NAME="antigravity-bridge"
REPO="suwei8/antigravity-Bridge"
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

_validate_display() {
    # 验证给定的 DISPLAY 是否可连通
    # 返回 0 表示可用，1 表示不可用
    local test_display="$1"
    if [ -z "$test_display" ]; then
        return 1
    fi
    DISPLAY="$test_display" xdpyinfo >/dev/null 2>&1
    return $?
}

setup_env() {
    local detected_display=""
    local candidates=()

    # 1. 从 X11 unix socket 获取候选（最可靠，排除 SSH X11 forwarding 的高端口号）
    local user_uid=$(id -u)
    for sock in $(find /tmp/.X11-unix/ -maxdepth 1 -name 'X*' 2>/dev/null | sort); do
        local num=$(echo "$sock" | sed 's|.*/X||')
        if [ -n "$num" ]; then
            candidates+=(":$num")
        fi
    done

    # 2. 如果当前环境有 DISPLAY，加入候选（但不一定优先，需验证）
    if [ -n "$DISPLAY" ]; then
        # 去重：如果已经在候选中就不重复添加
        local already=0
        for c in "${candidates[@]}"; do
            # 标准化比较（:10.0 vs :10）
            local norm_c=$(echo "$c" | sed 's/\.[0-9]*$//')
            local norm_d=$(echo "$DISPLAY" | sed 's/\.[0-9]*$//')
            if [ "$norm_c" = "$norm_d" ]; then
                already=1
                break
            fi
        done
        if [ $already -eq 0 ]; then
            candidates+=("$DISPLAY")
        fi
    fi

    # 3. 从 w 命令获取额外候选
    for d in $(w 2>/dev/null | grep -o ':[0-9]\+\(\.[0-9]\+\)\?' | sort -u); do
        local already=0
        for c in "${candidates[@]}"; do
            local norm_c=$(echo "$c" | sed 's/\.[0-9]*$//')
            local norm_d=$(echo "$d" | sed 's/\.[0-9]*$//')
            if [ "$norm_c" = "$norm_d" ]; then
                already=1
                break
            fi
        done
        if [ $already -eq 0 ]; then
            candidates+=("$d")
        fi
    done

    # 4. 兜底：加入 :0 和 :1
    for fallback in ":0" ":1"; do
        local already=0
        for c in "${candidates[@]}"; do
            if [ "$c" = "$fallback" ]; then
                already=1
                break
            fi
        done
        if [ $already -eq 0 ]; then
            candidates+=("$fallback")
        fi
    done

    # 5. 逐个验证，使用第一个可连通的 DISPLAY
    for candidate in "${candidates[@]}"; do
        if _validate_display "$candidate"; then
            detected_display="$candidate"
            break
        fi
    done

    if [ -z "$detected_display" ]; then
        # 全部验证失败，使用 :0 作为兜底（程序内部会处理连接失败）
        detected_display=":0"
        echo -e "${RED}[WARN] 未找到可用的 X11 DISPLAY，使用默认值 :0${NC}"
    fi

    export DISPLAY="$detected_display"
    export XAUTHORITY="$HOME/.Xauthority"
    info "检测并配置环境变量: DISPLAY=$DISPLAY, XAUTHORITY=$XAUTHORITY"

    # 强制更新或追加到 .env，以备其他场景读取
    if [ -f .env ]; then
        sed -i '/^DISPLAY=/d' .env 2>/dev/null || true
        sed -i '/^XAUTHORITY=/d' .env 2>/dev/null || true
        echo "DISPLAY=$DISPLAY" >> .env
        echo "XAUTHORITY=$XAUTHORITY" >> .env
    fi
}

deploy() {
    info "开始部署..."
    check_dependencies
    
    info "正在下载最新版本..."
    local tmp_file="${APP_NAME}.tmp"
    local download_url="https://github.com/${REPO}/releases/latest/download/${APP_NAME}"
    
    if wget -O "$tmp_file" "$download_url"; then
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

        # 获取当前 DISPLAY，优先从进程中或 w 命令检测，默认为 :0
        setup_env

        cat > "$MCP_CONFIG_FILE" << EOF
{
  "mcpServers": {
    "antigravity-bridge": {
      "command": "$APP_PATH",
      "args": [],
      "env": {
        "TELEGRAM_BOT_TOKEN": "$token",
        "TELEGRAM_CHAT_ID": "$chat_id",
        "DISPLAY": "$DISPLAY",
        "XAUTHORITY": "$XAUTHORITY"
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

    # 直接下载最新二进制文件
    info "正在下载最新版本二进制..."
    local tmp_file="${APP_NAME}.tmp"
    local download_url="https://github.com/${REPO}/releases/latest/download/${APP_NAME}"
    
    if wget -O "$tmp_file" "$download_url"; then
        chmod +x "$tmp_file"
        
        info "正在停止当前服务..."
        stop
        sleep 2
        
        info "替换可执行文件..."
        mv -f "$tmp_file" "$APP_NAME"
        
        info "更新成功，正在启动服务..."
        start
    else
        error "下载最新二进制文件失败，请检查网络。"
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

    # 再次检测并覆盖环境变量（防止 .env 中的值过时或缺失）
    setup_env

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
    info "正在停止所有相关进程..."
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        info "正在停止主程序 (PID: $pid)..."
        kill $pid 2>/dev/null
        rm -f "$PID_FILE"
    fi
    
    # 强制清理所有 antigravity-bridge 进程（包括 IDE 后台启动的）
    pkill -9 -f "antigravity-bridge" 2>/dev/null
    sleep 1
    
    # 再次检查
    if pgrep -f "antigravity-bridge" > /dev/null; then
        error "警告：仍有进程未能正常退出，请手动检查"
    else
        info "程序已停止。"
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

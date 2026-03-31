#!/usr/bin/env bash
#
# service.sh — Manage zim-rag as a macOS startup service (launchd)
#
# Usage:
#   ./service.sh install    Install and start zim-rag web UI on boot
#   ./service.sh uninstall  Stop and remove the startup service
#   ./service.sh start      Start the service now
#   ./service.sh stop       Stop the service now
#   ./service.sh restart    Restart the service
#   ./service.sh status     Show service status
#   ./service.sh logs       Show recent log output
#
# This creates two launchd services:
#   1. Ollama (via brew services — already handled by Homebrew)
#   2. zim-rag serve (custom plist)
#
# The web UI will be available at http://localhost:7860 after login.
#
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ─── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"
PLIST_NAME="com.zim-rag.serve"
PLIST_PATH="${HOME}/Library/LaunchAgents/${PLIST_NAME}.plist"
LOG_DIR="${HOME}/.zim-rag/logs"
STDOUT_LOG="${LOG_DIR}/serve.log"
STDERR_LOG="${LOG_DIR}/serve.err"

# ─── Validate environment ────────────────────────────────────────────────────
check_venv() {
    if [[ ! -f "${VENV_DIR}/bin/zim-rag" ]]; then
        error "zim-rag not installed. Run ./setup.sh first."
        exit 1
    fi
}

# ─── Generate plist ──────────────────────────────────────────────────────────
generate_plist() {
    # Read port from config, default to 7860
    local port=7860
    local host="127.0.0.1"
    if command -v python3 &>/dev/null; then
        port=$(python3 -c "
import yaml, os
try:
    with open(os.path.expanduser('~/.zim-rag/config.yaml')) as f:
        c = yaml.safe_load(f) or {}
    print(c.get('serve', {}).get('port', 7860))
except: print(7860)
" 2>/dev/null || echo "7860")
        host=$(python3 -c "
import yaml, os
try:
    with open(os.path.expanduser('~/.zim-rag/config.yaml')) as f:
        c = yaml.safe_load(f) or {}
    print(c.get('serve', {}).get('host', '127.0.0.1'))
except: print('127.0.0.1')
" 2>/dev/null || echo "127.0.0.1")
    fi

    cat > "$PLIST_PATH" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_NAME}</string>

    <key>ProgramArguments</key>
    <array>
        <string>${VENV_DIR}/bin/zim-rag</string>
        <string>serve</string>
        <string>--host</string>
        <string>${host}</string>
        <string>--port</string>
        <string>${port}</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>

    <key>StandardOutPath</key>
    <string>${STDOUT_LOG}</string>

    <key>StandardErrorPath</key>
    <string>${STDERR_LOG}</string>

    <key>WorkingDirectory</key>
    <string>${SCRIPT_DIR}</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>${VENV_DIR}/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key>
        <string>${HOME}</string>
    </dict>

    <key>ThrottleInterval</key>
    <integer>10</integer>

    <key>ProcessType</key>
    <string>Background</string>
</dict>
</plist>
PLIST_EOF

    # Secure the plist file permissions (owner read/write only)
    chmod 600 "$PLIST_PATH"
}

# ─── Commands ─────────────────────────────────────────────────────────────────
cmd_install() {
    check_venv
    mkdir -p "$LOG_DIR"
    chmod 700 "$LOG_DIR"
    mkdir -p "$(dirname "$PLIST_PATH")"

    # Ensure Ollama starts on boot
    if command -v brew &>/dev/null && command -v ollama &>/dev/null; then
        info "Enabling Ollama to start on login..."
        brew services start ollama 2>/dev/null || warn "Ollama service may already be running."
    fi

    info "Generating launchd plist..."
    generate_plist

    info "Loading service..."
    launchctl load "$PLIST_PATH" 2>/dev/null || true

    echo ""
    info "Service installed and started!"
    info "  Web UI: http://localhost:$(grep -A1 '<string>--port</string>' "$PLIST_PATH" | tail -1 | sed 's/.*<string>//' | sed 's/<.*//')"
    info "  Logs:   ${STDOUT_LOG}"
    info "  Errors: ${STDERR_LOG}"
    echo ""
    info "The web UI will start automatically on login."
    info "Run './service.sh uninstall' to remove."
}

cmd_uninstall() {
    if [[ -f "$PLIST_PATH" ]]; then
        info "Unloading service..."
        launchctl unload "$PLIST_PATH" 2>/dev/null || true
        rm -f "$PLIST_PATH"
        info "Service removed."
    else
        warn "Service not installed (${PLIST_PATH} not found)."
    fi

    echo ""
    echo "  Note: Ollama is managed separately. To stop it:"
    echo "    brew services stop ollama"
}

cmd_start() {
    if [[ ! -f "$PLIST_PATH" ]]; then
        error "Service not installed. Run './service.sh install' first."
        exit 1
    fi
    info "Starting zim-rag..."
    launchctl load "$PLIST_PATH" 2>/dev/null || true
    info "Started. Check status with './service.sh status'"
}

cmd_stop() {
    if [[ ! -f "$PLIST_PATH" ]]; then
        warn "Service not installed."
        return
    fi
    info "Stopping zim-rag..."
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    info "Stopped."
}

cmd_restart() {
    cmd_stop
    sleep 1
    cmd_start
}

cmd_status() {
    echo ""
    echo -e "${BOLD}zim-rag service status:${NC}"

    if [[ -f "$PLIST_PATH" ]]; then
        echo -e "  Plist:    ${GREEN}installed${NC} (${PLIST_PATH})"
    else
        echo -e "  Plist:    ${RED}not installed${NC}"
        echo ""
        return
    fi

    # Check if the process is running
    if launchctl list "$PLIST_NAME" &>/dev/null; then
        local pid
        pid=$(launchctl list "$PLIST_NAME" 2>/dev/null | awk 'NR==2{print $1}' || echo "-")
        local exit_code
        exit_code=$(launchctl list "$PLIST_NAME" 2>/dev/null | awk 'NR==2{print $2}' || echo "-")
        echo -e "  Status:   ${GREEN}loaded${NC} (PID: ${pid}, last exit: ${exit_code})"
    else
        echo -e "  Status:   ${YELLOW}not loaded${NC}"
    fi

    # Check Ollama
    if pgrep -x ollama &>/dev/null; then
        echo -e "  Ollama:   ${GREEN}running${NC}"
    else
        echo -e "  Ollama:   ${RED}not running${NC}"
    fi

    # Show port
    if [[ -f "$PLIST_PATH" ]]; then
        local port
        port=$(grep -A1 '<string>--port</string>' "$PLIST_PATH" 2>/dev/null | tail -1 | sed 's/.*<string>//' | sed 's/<.*//' || echo "7860")
        echo -e "  Web UI:   http://localhost:${port}"
    fi

    echo ""
}

cmd_logs() {
    if [[ -f "$STDOUT_LOG" ]]; then
        echo -e "${BOLD}=== Recent output (${STDOUT_LOG}) ===${NC}"
        tail -50 "$STDOUT_LOG"
    else
        warn "No log file found at ${STDOUT_LOG}"
    fi

    if [[ -f "$STDERR_LOG" ]] && [[ -s "$STDERR_LOG" ]]; then
        echo ""
        echo -e "${BOLD}=== Recent errors (${STDERR_LOG}) ===${NC}"
        tail -20 "$STDERR_LOG"
    fi
}

# ─── Main ─────────────────────────────────────────────────────────────────────
case "${1:-}" in
    install)    cmd_install ;;
    uninstall)  cmd_uninstall ;;
    start)      cmd_start ;;
    stop)       cmd_stop ;;
    restart)    cmd_restart ;;
    status)     cmd_status ;;
    logs)       cmd_logs ;;
    *)
        echo "Usage: $0 {install|uninstall|start|stop|restart|status|logs}"
        echo ""
        echo "  install    Install and start zim-rag web UI on boot"
        echo "  uninstall  Stop and remove the startup service"
        echo "  start      Start the service now"
        echo "  stop       Stop the service now"
        echo "  restart    Restart the service"
        echo "  status     Show service status"
        echo "  logs       Show recent log output"
        exit 1
        ;;
esac

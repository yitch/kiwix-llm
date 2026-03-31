#!/usr/bin/env bash
#
# One-line installer for zim-rag
#
# Usage:
#   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/yitch/kiwix-llm/main/install.sh)"
#
# What this does:
#   1. Clones the repo to ~/kiwix-llm
#   2. Runs setup.sh (installs Homebrew deps, Ollama, Python, models)
#   3. Downloads a starter Wikipedia ZIM file
#   4. Prints next steps
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

INSTALL_DIR="${HOME}/kiwix-llm"

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║     zim-rag: Offline Knowledge System    ║${NC}"
echo -e "${BOLD}║     One-Line Installer                   ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""

# ─── Check prerequisites ─────────────────────────────────────────────────────
if [[ "$(uname)" != "Darwin" ]]; then
    error "This installer is for macOS only."
    exit 1
fi

if ! command -v git &>/dev/null; then
    error "git is required. Install Xcode Command Line Tools:"
    echo "  xcode-select --install"
    exit 1
fi

# ─── Clone or update repo ────────────────────────────────────────────────────
if [[ -d "$INSTALL_DIR" ]]; then
    info "Directory ${INSTALL_DIR} already exists. Updating..."
    cd "$INSTALL_DIR"
    git pull --ff-only origin main 2>/dev/null || warn "Could not pull latest changes. Continuing with existing code."
else
    info "Cloning kiwix-llm to ${INSTALL_DIR}..."
    git clone https://github.com/yitch/kiwix-llm.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

chmod +x setup.sh download-zims.sh

# ─── Run setup ────────────────────────────────────────────────────────────────
info "Running setup (this installs Homebrew packages, Ollama, Python, and models)..."
echo ""
./setup.sh

# ─── Download starter ZIM ────────────────────────────────────────────────────
echo ""
info "Downloading starter Wikipedia ZIM (~2GB)..."
echo ""
./download-zims.sh wikipedia

# ─── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║     Setup complete! You're ready to go.  ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════╝${NC}"
echo ""
echo "  To get started:"
echo ""
echo -e "    ${BOLD}cd ~/kiwix-llm${NC}"
echo -e "    ${BOLD}source .venv/bin/activate${NC}"
echo -e "    ${BOLD}ollama serve &${NC}                # start Ollama (if not running)"
echo ""
echo "  Then ingest Wikipedia and ask a question:"
echo ""
echo -e "    ${BOLD}zim-rag ingest ~/zim-files/wikipedia_en_top_maxi_2024-10.zim${NC}"
echo -e "    ${BOLD}zim-rag query \"What causes earthquakes?\"${NC}"
echo ""
echo "  Or launch the web UI:"
echo ""
echo -e "    ${BOLD}zim-rag serve${NC}"
echo ""

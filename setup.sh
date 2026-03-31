#!/usr/bin/env bash
#
# setup.sh — Install all prerequisites for zim-rag on macOS (Apple Silicon)
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
#
# What this does:
#   1. Installs Homebrew (if missing)
#   2. Installs Ollama and kiwix-tools via Homebrew
#   3. Pulls the required Ollama models
#   4. Installs Python 3.11+ (if missing)
#   5. Creates a virtualenv and installs zim-rag
#   6. Copies the default config
#
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

OLLAMA_PID=""

cleanup() {
    if [[ -n "$OLLAMA_PID" ]]; then
        info "Cleaning up: stopping Ollama (PID ${OLLAMA_PID})..."
        kill "$OLLAMA_PID" 2>/dev/null || true
        wait "$OLLAMA_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# ─── Check macOS ──────────────────────────────────────────────────────────────
if [[ "$(uname)" != "Darwin" ]]; then
    error "This script is designed for macOS. For Linux, adapt the Homebrew steps."
    exit 1
fi

# ─── Homebrew ─────────────────────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
    info "Installing Homebrew..."
    # Note: this fetches and runs a remote script — the standard Homebrew install method.
    # Verify at https://brew.sh if concerned.
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    # Add to path for Apple Silicon
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    fi
else
    info "Homebrew already installed."
fi

# ─── Ollama ───────────────────────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
    info "Installing Ollama..."
    brew install ollama
else
    info "Ollama already installed: $(ollama --version 2>/dev/null || echo 'unknown version')"
fi

# ─── kiwix-tools ──────────────────────────────────────────────────────────────
if ! command -v kiwix-serve &>/dev/null; then
    info "Installing kiwix-tools..."
    brew install kiwix-tools
else
    info "kiwix-tools already installed."
fi

# ─── Python ───────────────────────────────────────────────────────────────────
PYTHON=""
for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [[ "$major" -ge 3 && "$minor" -ge 11 ]]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    info "Installing Python 3.12 via Homebrew..."
    brew install python@3.12
    PYTHON="python3.12"
fi
info "Using Python: $($PYTHON --version)"

# ─── Virtual environment ─────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${SCRIPT_DIR}/.venv"

if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment at ${VENV_DIR}..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

source "${VENV_DIR}/bin/activate"
info "Virtual environment activated."

# ─── Install zim-rag ──────────────────────────────────────────────────────────
info "Installing zim-rag and dependencies..."
pip install --upgrade pip
pip install -e "${SCRIPT_DIR}"

# ─── Config ───────────────────────────────────────────────────────────────────
CONFIG_DIR="$HOME/.zim-rag"
mkdir -p "$CONFIG_DIR"

if [[ ! -f "${CONFIG_DIR}/config.yaml" ]]; then
    info "Copying default config to ${CONFIG_DIR}/config.yaml"
    cp "${SCRIPT_DIR}/config.example.yaml" "${CONFIG_DIR}/config.yaml"
else
    info "Config already exists at ${CONFIG_DIR}/config.yaml"
fi

# ─── ZIM directory ────────────────────────────────────────────────────────────
ZIM_DIR="$HOME/zim-files"
mkdir -p "$ZIM_DIR"

# ─── Start Ollama and pull models ─────────────────────────────────────────────
STARTED_OLLAMA=false
if ! pgrep -x "ollama" &>/dev/null; then
    info "Starting Ollama service..."
    ollama serve &>/dev/null &
    OLLAMA_PID=$!

    # Wait for readiness instead of fixed sleep
    for i in $(seq 1 15); do
        if curl -sf http://localhost:11434/api/tags &>/dev/null; then
            info "Ollama is ready."
            STARTED_OLLAMA=true
            break
        fi
        sleep 1
    done

    if [[ "$STARTED_OLLAMA" = false ]]; then
        warn "Ollama did not respond after 15s. Model pulls may fail."
        warn "Try running 'ollama serve' manually in another terminal."
    fi
else
    info "Ollama already running."
fi

info "Pulling embedding model (nomic-embed-text)..."
ollama pull nomic-embed-text

# Detect RAM and suggest a model
RAM_GB=$(sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.0f", $1/1073741824}')
if [[ "$RAM_GB" -ge 32 ]]; then
    LLM_MODEL="qwen3:14b"
elif [[ "$RAM_GB" -ge 24 ]]; then
    LLM_MODEL="mistral-small"
elif [[ "$RAM_GB" -ge 16 ]]; then
    LLM_MODEL="qwen3:8b"
else
    LLM_MODEL="qwen3:4b"
fi

info "Detected ${RAM_GB}GB RAM. Pulling recommended LLM: ${LLM_MODEL}..."
ollama pull "$LLM_MODEL"

# Update config with detected model (LLM_MODEL is from a hardcoded set, safe for sed)
if command -v sed &>/dev/null; then
    sed -i '' "s/llm_model: .*/llm_model: \"${LLM_MODEL}\"/" "${CONFIG_DIR}/config.yaml" 2>/dev/null || true
fi

# If we started Ollama, stop it — user can start it themselves
if [[ -n "$OLLAMA_PID" ]]; then
    info "Stopping setup-started Ollama (PID ${OLLAMA_PID})..."
    kill "$OLLAMA_PID" 2>/dev/null || true
    wait "$OLLAMA_PID" 2>/dev/null || true
    OLLAMA_PID=""  # Clear so trap doesn't double-kill
fi

# ─── Done ─────────────────────────────────────────────────────────────────────
echo ""
info "=========================================="
info "  zim-rag setup complete!"
info "=========================================="
echo ""
echo "  Next steps:"
echo ""
echo "  1. Activate the virtualenv:"
echo "     source ${VENV_DIR}/bin/activate"
echo ""
echo "  2. Start Ollama (if not already running):"
echo "     ollama serve"
echo ""
echo "  3. Download some ZIM files:"
echo "     ./download-zims.sh"
echo ""
echo "  4. Ingest a ZIM file:"
echo "     zim-rag ingest ~/zim-files/wikipedia_en_top_maxi_2024-10.zim"
echo ""
echo "  5. Ask a question:"
echo "     zim-rag query \"What is photosynthesis?\""
echo ""
echo "  6. Or start the web UI:"
echo "     zim-rag serve"
echo ""
echo "  Config file: ${CONFIG_DIR}/config.yaml"
echo "  LLM model:   ${LLM_MODEL} (edit config to change)"
echo ""

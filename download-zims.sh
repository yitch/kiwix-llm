#!/usr/bin/env bash
#
# download-zims.sh — Download useful starter ZIM files from the Kiwix library
#
# Usage:
#   chmod +x download-zims.sh
#   ./download-zims.sh           # Download all recommended ZIMs
#   ./download-zims.sh wikipedia # Download just Wikipedia
#
# These are smaller/curated ZIM files suitable for getting started.
# For the full Wikipedia (~100GB), visit: https://wiki.kiwix.org/wiki/Content
#
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

ZIM_DIR="${HOME}/zim-files"
mkdir -p "$ZIM_DIR"

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

check_disk_space() {
    # Check available space in GB at the ZIM_DIR mount point
    local available_kb
    available_kb=$(df -k "$ZIM_DIR" | tail -1 | awk '{print $4}')
    local available_gb=$(( available_kb / 1048576 ))
    if [[ "$available_gb" -lt 3 ]]; then
        warn "Low disk space: only ${available_gb}GB available at ${ZIM_DIR}"
        warn "Some downloads may require several GB. Continue? [y/N]"
        read -r response
        if [[ "$response" != "y" && "$response" != "Y" ]]; then
            info "Aborted."
            exit 0
        fi
    fi
}

download() {
    local name="$1"
    local url="$2"
    local filename
    filename=$(basename "$url")
    local dest="${ZIM_DIR}/${filename}"
    local part="${dest}.part"

    if [[ -f "$dest" ]]; then
        info "${name}: already downloaded (${dest})"
        return
    fi

    info "Downloading ${name}..."
    info "  URL: ${url}"
    info "  Destination: ${dest}"
    echo ""

    # Download to a .part file, then rename on success
    # This prevents partial/corrupt downloads from being mistaken as complete
    local download_ok=false
    if command -v curl &>/dev/null; then
        if curl -L --fail --progress-bar -o "$part" "$url"; then
            download_ok=true
        fi
    elif command -v wget &>/dev/null; then
        if wget --show-progress -O "$part" "$url"; then
            download_ok=true
        fi
    else
        error "Neither curl nor wget found. Please install one and retry."
        return 1
    fi

    if [[ "$download_ok" = true && -f "$part" ]]; then
        mv "$part" "$dest"
        info "${name}: download complete!"
    else
        error "${name}: download failed."
        rm -f "$part"
        warn "The URL may have changed. Check https://download.kiwix.org/zim/ for current filenames."
        return 1
    fi
    echo ""
}

# Clean up partial downloads on interrupt
cleanup() {
    echo ""
    warn "Download interrupted. Cleaning up partial files..."
    rm -f "${ZIM_DIR}"/*.part
    exit 1
}
trap cleanup INT TERM

# ─── ZIM File Catalog ────────────────────────────────────────────────────────
# Note: These URLs point to the Kiwix download server.
# Check https://download.kiwix.org/zim/ for the latest versions.
# File names and dates change over time — if a download fails, visit
# the URL directory in your browser to find the current filename.

# Wikipedia English — "top" subset (~2GB, top ~50k articles)
WIKIPEDIA_URL="https://download.kiwix.org/zim/wikipedia/wikipedia_en_top_maxi_2024-10.zim"

# WikiMed — Medical articles from Wikipedia (~1GB)
WIKIMED_URL="https://download.kiwix.org/zim/wikipedia/wikipedia_en_medicine_maxi_2024-10.zim"

# Stack Exchange — various sites
STACKOVERFLOW_URL="https://download.kiwix.org/zim/stack_exchange/superuser.com_en_all_2024-09.zim"

# Wiktionary English (~1.5GB)
WIKTIONARY_URL="https://download.kiwix.org/zim/wiktionary/wiktionary_en_all_maxi_2024-10.zim"

# ─── Download Logic ──────────────────────────────────────────────────────────

FILTER="${1:-all}"

echo "============================================"
echo " zim-rag: ZIM File Downloader"
echo " Download directory: ${ZIM_DIR}"
echo "============================================"
echo ""

check_disk_space

case "$FILTER" in
    all)
        download "Wikipedia EN (Top Articles)" "$WIKIPEDIA_URL"
        download "WikiMed (Medical)" "$WIKIMED_URL"
        download "Super User (Stack Exchange)" "$STACKOVERFLOW_URL"
        download "Wiktionary EN" "$WIKTIONARY_URL"
        ;;
    wikipedia)
        download "Wikipedia EN (Top Articles)" "$WIKIPEDIA_URL"
        ;;
    wikimed|medical)
        download "WikiMed (Medical)" "$WIKIMED_URL"
        ;;
    stackoverflow|stackexchange)
        download "Super User (Stack Exchange)" "$STACKOVERFLOW_URL"
        ;;
    wiktionary)
        download "Wiktionary EN" "$WIKTIONARY_URL"
        ;;
    *)
        echo "Usage: $0 [all|wikipedia|wikimed|stackoverflow|wiktionary]"
        exit 1
        ;;
esac

echo ""
echo "============================================"
info "Downloads complete!"
echo ""
echo "  ZIM files are in: ${ZIM_DIR}"
echo ""
echo "  Next: ingest them into the knowledge base:"
echo "    zim-rag ingest ${ZIM_DIR}/<filename>.zim"
echo ""
echo "  Or browse them directly with kiwix-serve:"
echo "    kiwix-serve --port 8888 ${ZIM_DIR}/*.zim"
echo "============================================"

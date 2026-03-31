"""Web UI server using Gradio, with optional kiwix-serve integration."""

from __future__ import annotations

import logging
import subprocess
import signal
import sys
import time
from pathlib import Path

from rich.console import Console

from zim_rag.config import Config, MAX_QUERY_LENGTH
from zim_rag.query import query_rag_simple

console = Console()
logger = logging.getLogger(__name__)

CUSTOM_CSS = """
/* Header toolbar */
#header-toolbar {
    display: flex !important;
    justify-content: flex-end !important;
    align-items: center !important;
    gap: 0.5rem !important;
    padding: 0.75rem 0 0.25rem 0 !important;
}
#header-toolbar > * {
    flex: 0 0 auto !important;
    min-width: 0 !important;
}
#header-toolbar button {
    border-radius: 20px !important;
    font-size: 0.85rem !important;
    padding: 0.4rem 1rem !important;
}

/* ZIM path display panel */
#zim-path-display {
    border-radius: 8px;
    padding: 0.75rem 1rem;
    margin: 0.25rem 0 0.5rem 0;
    font-size: 0.9rem;
}

/* Chat area */
.chatbot {
    border-radius: 12px !important;
    min-height: 500px !important;
}

/* Status bar */
#status-bar {
    text-align: center;
    opacity: 0.5;
    font-size: 0.8rem;
    padding: 0.5rem 0;
}

/* Example buttons */
.example-btn {
    border-radius: 20px !important;
    font-size: 0.85rem !important;
}
"""

DARK_MODE_JS = """
(function() {
    'use strict';
    if (window.__zimragDarkMode) return;
    window.__zimragDarkMode = true;

    const STORAGE_KEY = 'zim-rag-dark';

    function applyDarkMode(enable) {
        if (enable) {
            document.body.classList.add('dark');
        } else {
            document.body.classList.remove('dark');
        }
        localStorage.setItem(STORAGE_KEY, enable ? '1' : '0');
        updateButton(enable);
    }

    function updateButton(isDark) {
        const doUpdate = function() {
            const el = document.getElementById('zimrag-theme-btn');
            const btn = el ? (el.tagName === 'BUTTON' ? el : el.querySelector('button')) : null;
            if (btn) {
                btn.textContent = isDark ? '☀️ Light Mode' : '🌙 Dark Mode';
            }
        };
        doUpdate();
        setTimeout(doUpdate, 300);
        setTimeout(doUpdate, 800);
    }

    window.zimragToggleTheme = function() {
        const isDark = document.body.classList.contains('dark');
        applyDarkMode(!isDark);
    };

    function init() {
        const saved = localStorage.getItem(STORAGE_KEY);
        const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        const shouldBeDark = saved ? saved === '1' : prefersDark;
        applyDarkMode(shouldBeDark);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
"""

DARK_TOGGLE_HTML = """
<button id="zimrag-theme-btn" onclick="window.zimragToggleTheme(); return false;" 
    style="border-radius: 20px; padding: 0.4rem 1rem; font-size: 0.85rem; cursor: pointer; border: 1px solid #ccc; background: var(--button-secondary-background-fill, #f0f0f0);">
    🌙 Dark Mode
</button>
<script>
    // Immediate inline script to set correct button text before page renders
    (function() {
        const saved = localStorage.getItem('zim-rag-dark');
        const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        const isDark = saved ? saved === '1' : prefersDark;
        const btn = document.getElementById('zimrag-theme-btn');
        if (btn) {
            btn.innerHTML = isDark ? '☀️ Light Mode' : '🌙 Dark Mode';
        }
    })();
</script>
"""


def _list_zim_files(folder: str) -> str:
    """Return a markdown summary of .zim files in a folder."""
    zim_dir = Path(folder)
    if not zim_dir.is_dir():
        return f"**ZIM Folder:** `{folder}`\n\n\u26a0\ufe0f Directory not found."

    zims = sorted(p.name for p in zim_dir.glob("*.zim") if p.is_file())
    if not zims:
        return (
            f"**ZIM Folder:** `{folder}`\n\n"
            "No `.zim` files found. Download some with `./download-zims.sh` "
            "or place `.zim` files in this folder."
        )

    file_list = "\n".join(f"- `{z}`" for z in zims)
    return f"**ZIM Folder:** `{folder}`\n\n**{len(zims)} ZIM file(s):**\n{file_list}"


def _pick_folder_macos(current_dir: str) -> str:
    """Open a native macOS folder picker. Returns selected path or current_dir on cancel.

    Uses osascript with argv to avoid script-injection risks — the path is
    never interpolated into the AppleScript source.
    """
    script = (
        "on run argv\n"
        "    set defaultDir to POSIX file (item 1 of argv)\n"
        "    POSIX path of (choose folder with prompt "
        '"Select ZIM Files Folder" default location defaultDir)\n'
        "end run\n"
    )
    try:
        result = subprocess.run(
            ["osascript", "-", current_dir],
            input=script,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            chosen = result.stdout.strip().rstrip("/")
            if Path(chosen).is_dir():
                return chosen
    except (subprocess.TimeoutExpired, OSError):
        pass
    return current_dir


def _run_ingestion_stream(zim_dir: str, config: Config):
    """Generator that runs ingestion and yields progress updates.
    
    Yields: (status_message, is_running, has_error)
    - status_message: str message to display
    - is_running: bool - True if ingestion is still running
    - has_error: bool - True if there was an error
    """
    import threading
    import queue
    from zim_rag.ingest import ingest_zim, _zim_priority_key

    zim_path = Path(zim_dir)
    if not zim_path.is_dir():
        yield "❌ Error: Invalid ZIM folder", False, True
        return

    zim_files = sorted(
        (p for p in zim_path.glob("*.zim") if p.is_file()),
        key=_zim_priority_key
    )
    if not zim_files:
        yield "❌ No .zim files found in folder", False, True
        return

    total_files = len(zim_files)
    status_queue = queue.Queue()
    
    def ingest_worker():
        try:
            for i, zim_file in enumerate(zim_files, 1):
                priority = _zim_priority_key(zim_file)[0]
                priority_label = {0: "★★★", 1: "★★☆", 2: "★☆☆"}[priority]
                status_queue.put(('status', f"{priority_label} Ingesting {zim_file.name} ({i}/{total_files})..."))
                try:
                    ingest_zim(str(zim_file), config)
                    status_queue.put(('done_file', zim_file.name))
                except Exception as e:
                    status_queue.put(('error', f"Error ingesting {zim_file.name}: {e}"))
            status_queue.put(('complete', None))
        except Exception as e:
            status_queue.put(('error', str(e)))

    # Start ingestion in background thread
    thread = threading.Thread(target=ingest_worker, daemon=True)
    thread.start()

    completed = []
    errors = []
    
    # Stream status updates
    while True:
        try:
            msg_type, msg = status_queue.get(timeout=0.5)
            if msg_type == 'status':
                yield msg, True, False
            elif msg_type == 'done_file':
                completed.append(msg)
            elif msg_type == 'error':
                errors.append(msg)
                yield f"⚠️ {msg}", True, False
            elif msg_type == 'complete':
                break
        except queue.Empty:
            yield "", True, False  # Keep alive (empty message = no update)
            continue

    # Final status
    if errors:
        yield f"✅ Completed {len(completed)}/{total_files} files with {len(errors)} errors", False, bool(errors)
    else:
        yield f"✅ All {total_files} file(s) ingested successfully! You can now ask questions.", False, False


def _is_path_like_title(title: str) -> bool:
    """Check if a title looks like a ZIM path rather than a real article title.

    Path-like titles are things like "a/100723", "A/Some_Page", "I/image.png".
    Real titles are human-readable strings like "Photosynthesis" or "How CPUs work".
    """
    import re
    if not title:
        return True
    # Single-letter prefix followed by slash and digits (e.g. "a/100723")
    if re.match(r"^[a-zA-Z]/\d+$", title):
        return True
    # Single-letter prefix followed by slash (e.g. "A/Some_Page", "I/image")
    if re.match(r"^[A-Z]/", title) and len(title) < 5:
        return True
    return False


def _friendly_zim_name(zim_filename: str) -> str:
    """Convert a ZIM filename to a human-friendly source name.

    e.g. "electronics.stackexchange.com_en_all_2026-02.zim" -> "Electronics StackExchange"
         "wikipedia_en_all_maxi_2026-02.zim" -> "Wikipedia (en)"
    """
    name = zim_filename.replace(".zim", "")
    # Wikipedia pattern
    if name.startswith("wikipedia_"):
        parts = name.split("_")
        lang = parts[1] if len(parts) > 1 else ""
        return f"Wikipedia ({lang})"
    # StackExchange pattern: "electronics.stackexchange.com_en_all_2026-02"
    if ".stackexchange.com" in name:
        site = name.split(".stackexchange.com")[0]
        return f"{site.capitalize()} StackExchange"
    # Other: strip date suffix and clean up
    import re
    name = re.sub(r"_\d{4}-\d{2}$", "", name)
    name = re.sub(r"_en_all$", "", name)
    return name.replace("_", " ").replace(".", " ").strip().title()


def _format_source_citations(chunks: list[dict], max_sources: int) -> str:
    """Format source citations from retrieved chunks.

    Groups sources by ZIM file. Shows real article titles when available,
    and falls back to a friendly ZIM source name when titles are path-like.
    Returns a markdown string for the Sources section, or "" if no chunks.
    """
    if not chunks:
        return ""

    from collections import defaultdict

    # Group chunks by ZIM file, collecting real titles
    zim_titles: dict[str, list[str]] = defaultdict(list)
    seen_titles: set[str] = set()

    for chunk in chunks:
        meta = chunk.get("metadata", {})
        title = meta.get("title", "")
        zim = meta.get("zim_filename", "Unknown")

        if title and not _is_path_like_title(title) and title not in seen_titles:
            seen_titles.add(title)
            zim_titles[zim].append(title)
        elif zim not in zim_titles:
            zim_titles[zim] = []

    # Limit to max_sources ZIM files
    zim_list = list(zim_titles.keys())[:max_sources]

    lines: list[str] = []
    for zim in zim_list:
        friendly = _friendly_zim_name(zim)
        titles = zim_titles[zim]
        if titles:
            # Show up to 3 real article titles per source
            shown = titles[:3]
            title_str = ", ".join(shown)
            if len(titles) > 3:
                title_str += f" (+{len(titles) - 3} more)"
            lines.append(f"- **{friendly}**: {title_str}")
        else:
            lines.append(f"- **{friendly}**")

    if not lines:
        return ""
    return "\n\n---\n**Sources:**\n" + "\n".join(lines)


def build_ui(config: Config):
    """Build a polished Gradio chat interface with dark/light mode support."""
    import gradio as gr

    def respond(message: str, history: list) -> str:
        if not message or not message.strip():
            return ""
        if len(message) > MAX_QUERY_LENGTH:
            return f"Question too long (max {MAX_QUERY_LENGTH:,} characters). Please shorten it."

        try:
            answer, chunks = query_rag_simple(message, config)
        except Exception as e:
            logger.error("Query failed: %s", e)
            return "Something went wrong. Please check that Ollama is running (`ollama serve`)."

        citation = _format_source_citations(chunks, config.max_sources)
        if citation:
            answer += citation

        return answer

    def scan_folder(folder_str: str):
        """Scan a folder for .zim files and populate the dropdown."""
        zim_dir = Path(folder_str)
        if not zim_dir.is_dir():
            return gr.update(choices=[], value=None), gr.update(visible=False), gr.update(visible=False, value="")
        zims = sorted(p.name for p in zim_dir.glob("*.zim") if p.is_file())
        has_zims = len(zims) > 0
        return (
            gr.update(choices=zims, value=zims[0] if zims else None),
            gr.update(visible=has_zims),
            gr.update(visible=False, value=""),
        )

    def start_ingestion(folder_str: str):
        """Generator that streams ingestion progress."""
        for status_msg, is_running, has_error in _run_ingestion_stream(folder_str, config):
            if status_msg == "":
                yield gr.skip(), gr.skip()
            else:
                yield gr.update(value=status_msg, visible=True), gr.update(interactive=not is_running)

    with gr.Blocks() as app:
        # ── Header toolbar ────────────────────────────────────────────
        with gr.Row(elem_id="header-toolbar"):
            dark_btn = gr.Button(
                "\U0001f319 Dark Mode", variant="secondary", size="sm",
                elem_id="zimrag-theme-btn",
            )
        dark_btn.click(fn=None, js="() => window.zimragToggleTheme()")

        # ── ZIM Files & Ingest (collapsible) ──────────────────────────
        with gr.Accordion("\U0001f4c2 ZIM Files & Ingest", open=False):
            with gr.Row():
                folder_path = gr.Textbox(
                    value=config.zim_dir,
                    label="ZIM Folder Path",
                    scale=4,
                    interactive=True,
                )
                scan_btn = gr.Button("\U0001f50d Scan", variant="secondary", scale=1)

            zim_dropdown = gr.Dropdown(label="ZIM Files Found", choices=[], interactive=True)
            ingest_btn = gr.Button("\U0001f680 Start Ingest", variant="primary", visible=False)
            ingest_log = gr.Textbox(label="Ingest Log", interactive=False, visible=False, lines=5)

        scan_btn.click(
            fn=scan_folder,
            inputs=[folder_path],
            outputs=[zim_dropdown, ingest_btn, ingest_log],
        )
        ingest_btn.click(
            fn=start_ingestion,
            inputs=[folder_path],
            outputs=[ingest_log, ingest_btn],
        )

        # ── Chat ──────────────────────────────────────────────────────
        gr.ChatInterface(
            fn=respond,
            title="zim-rag",
            description=(
                "Offline Knowledge Assistant \u2014 ask questions against your locally ingested "
                "ZIM knowledge base."
            ),
            examples=[
                "What is photosynthesis?",
                "Explain how TCP/IP works",
                "What are the symptoms of diabetes?",
                "How does a CPU work?",
            ],
            fill_height=False,
        )

    return app


def start_kiwix_serve(config: Config, zim_paths: list[str]) -> subprocess.Popen | None:
    """Start kiwix-serve as a subprocess for browsing ZIM files."""
    import shutil

    kiwix = shutil.which("kiwix-serve")
    if not kiwix:
        console.print("[yellow]kiwix-serve not found. Install with: brew install kiwix-tools[/yellow]")
        return None

    if not zim_paths:
        zim_dir = Path(config.zim_dir)
        if zim_dir.exists():
            zim_paths = [
                str(p) for p in zim_dir.glob("*.zim")
                if p.is_file() and not p.is_symlink()
            ]

    if not zim_paths:
        console.print("[yellow]No ZIM files found. kiwix-serve not started.[/yellow]")
        return None

    cmd = [kiwix, "--port", str(config.kiwix_port)] + zim_paths
    console.print(f"[bold]Starting kiwix-serve on port {config.kiwix_port}...[/bold]")
    console.print(f"  Browse articles at: http://localhost:{config.kiwix_port}")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    time.sleep(1)
    if proc.poll() is not None:
        stderr_output = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        console.print(f"[red]kiwix-serve failed to start (exit code {proc.returncode})[/red]")
        if stderr_output:
            console.print(f"[red]{stderr_output[:500]}[/red]")
        return None

    return proc


def _terminate_process(proc: subprocess.Popen) -> None:
    """Gracefully terminate a subprocess, falling back to kill."""
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def serve(
    config: Config | None = None,
    kiwix_browse: bool = False,
    share: bool = False,
) -> None:
    """Launch the Gradio web UI, optionally with kiwix-serve."""
    import gradio as gr

    if config is None:
        config = Config.load()

    kiwix_proc = None
    if kiwix_browse:
        kiwix_proc = start_kiwix_serve(config, [])

    app = build_ui(config)

    console.print(f"[bold green]Starting web UI on http://{config.host}:{config.port}[/bold green]")

    def cleanup(signum=None, frame=None):
        if kiwix_proc and kiwix_proc.poll() is None:
            console.print("\n[dim]Stopping kiwix-serve...[/dim]")
            _terminate_process(kiwix_proc)
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # Prepare head HTML with the dark mode script
    head_html = f"<script>{DARK_MODE_JS}</script>"
    
    try:
        app.launch(
            server_name=config.host,
            server_port=config.port,
            share=share,
            show_error=True,
            theme=gr.themes.Soft(
                primary_hue="blue",
                secondary_hue="slate",
                neutral_hue="slate",
            ),
            css=CUSTOM_CSS,
            head=head_html,
        )
    finally:
        if kiwix_proc and kiwix_proc.poll() is None:
            _terminate_process(kiwix_proc)

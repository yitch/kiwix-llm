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
/* Overall polish */
.gradio-container {
    max-width: 900px !important;
    margin: 0 auto !important;
}

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

/* Dark mode toggle switch */
.dark-toggle-wrap {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 4px 8px;
}
.toggle-icon { font-size: 1rem; line-height: 1; }
.toggle-switch {
    position: relative;
    display: inline-block;
    width: 40px;
    height: 22px;
}
.toggle-switch input {
    opacity: 0;
    width: 0;
    height: 0;
    position: absolute;
}
.toggle-slider {
    position: absolute;
    cursor: pointer;
    inset: 0;
    background: #b0b0b0;
    border-radius: 22px;
    transition: 0.3s;
}
.toggle-slider:before {
    content: "";
    position: absolute;
    height: 16px;
    width: 16px;
    left: 3px;
    bottom: 3px;
    background: white;
    border-radius: 50%;
    transition: 0.3s;
}
.toggle-switch input:checked + .toggle-slider {
    background: #4f6cf7;
}
.toggle-switch input:checked + .toggle-slider:before {
    transform: translateX(18px);
}

/* ZIM path display panel */
#zim-path-display {
    border-radius: 8px;
    padding: 0.75rem 1rem;
    margin: 0.25rem 0 0.5rem 0;
    font-size: 0.9rem;
    background: var(--block-background-fill);
    border: 1px solid var(--border-color-primary);
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
() => {
    const stored = localStorage.getItem('zim-rag-dark-mode');
    let isDark;
    if (stored !== null) {
        isDark = stored === 'true';
    } else {
        isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    }
    if (isDark) {
        document.body.classList.add('dark');
    } else {
        document.body.classList.remove('dark');
    }

    window.toggleDarkMode = function() {
        const dark = document.body.classList.toggle('dark');
        localStorage.setItem('zim-rag-dark-mode', dark);
        const cb = document.getElementById('dark-toggle-cb');
        if (cb) cb.checked = dark;
    };

    setTimeout(() => {
        const cb = document.getElementById('dark-toggle-cb');
        if (cb) cb.checked = document.body.classList.contains('dark');
    }, 200);
}
"""

DARK_TOGGLE_HTML = """
<div class="dark-toggle-wrap">
    <span class="toggle-icon">\u2600\ufe0f</span>
    <label class="toggle-switch">
        <input type="checkbox" id="dark-toggle-cb"
               onchange="window.toggleDarkMode && window.toggleDarkMode()">
        <span class="toggle-slider"></span>
    </label>
    <span class="toggle-icon">\U0001f319</span>
</div>
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

        # Append source citations
        sources: list[str] = []
        seen: set[str] = set()
        for chunk in chunks:
            title = chunk["metadata"].get("title", "Unknown")
            zim = chunk["metadata"].get("zim_filename", "")
            if title not in seen:
                seen.add(title)
                sources.append(f"- **{title}** _{zim}_")

        if sources:
            answer += "\n\n---\n**Sources:**\n" + "\n".join(sources)

        return answer

    def pick_zim_folder(current_dir: str):
        if sys.platform == "darwin":
            new_dir = _pick_folder_macos(current_dir)
        else:
            new_dir = current_dir
        return new_dir, gr.update(value=_list_zim_files(new_dir), visible=True)

    with gr.Blocks(fill_height=True) as app:
        with gr.Row(elem_id="header-toolbar"):
            zim_btn = gr.Button("\U0001f4c2 ZIM Folder", variant="secondary", size="sm")
            gr.HTML(DARK_TOGGLE_HTML)

        zim_dir_state = gr.State(config.zim_dir)
        zim_panel = gr.Markdown("", elem_id="zim-path-display", visible=False)

        zim_btn.click(
            fn=pick_zim_folder,
            inputs=[zim_dir_state],
            outputs=[zim_dir_state, zim_panel],
        )

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
            fill_height=True,
            autofocus=True,
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
            js=DARK_MODE_JS,
        )
    finally:
        if kiwix_proc and kiwix_proc.poll() is None:
            _terminate_process(kiwix_proc)

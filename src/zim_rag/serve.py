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

/* Header area */
#header {
    text-align: center;
    padding: 1.5rem 0 0.5rem 0;
}
#header h1 {
    font-size: 1.8rem;
    font-weight: 700;
    margin-bottom: 0.25rem;
}
#header p {
    opacity: 0.7;
    font-size: 0.95rem;
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

    app = gr.ChatInterface(
        fn=respond,
        title="zim-rag",
        description=(
            "Offline Knowledge Assistant — ask questions against your locally ingested "
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
        )
    finally:
        if kiwix_proc and kiwix_proc.poll() is None:
            _terminate_process(kiwix_proc)

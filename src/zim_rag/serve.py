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


def build_ui(config: Config):
    """Build the Gradio interface."""
    import gradio as gr

    def answer_question(question: str, history: list) -> str:
        if not question.strip():
            return ""
        if len(question) > MAX_QUERY_LENGTH:
            return f"Question too long (max {MAX_QUERY_LENGTH:,} characters)."

        answer, chunks = query_rag_simple(question, config)

        # Append source citations
        sources: list[str] = []
        seen: set[str] = set()
        for chunk in chunks:
            title = chunk["metadata"].get("title", "Unknown")
            zim = chunk["metadata"].get("zim_filename", "")
            if title not in seen:
                seen.add(title)
                sources.append(f"- **{title}** ({zim})")

        if sources:
            answer += "\n\n---\n**Sources:**\n" + "\n".join(sources)

        return answer

    with gr.Blocks(
        title="zim-rag: Offline Knowledge Assistant",
        theme=gr.themes.Soft(),
    ) as app:
        gr.Markdown(
            "# zim-rag: Offline Knowledge Assistant\n"
            "Ask questions against your locally ingested ZIM knowledge base. "
            "Powered by Ollama + ChromaDB."
        )

        chatbot = gr.ChatInterface(
            fn=answer_question,
            type="messages",
            title="",
            examples=[
                "What is photosynthesis?",
                "Explain how TCP/IP works",
                "What are the symptoms of diabetes?",
            ],
        )

        gr.Markdown(
            f"*Model: {config.llm_model} | "
            f"Embeddings: {config.embed_model} | "
            f"Top-K: {config.top_k}*"
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
        # Try to find ZIM files in the configured directory
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

    # Check that the process didn't immediately fail
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
            show_error=False,
        )
    finally:
        if kiwix_proc and kiwix_proc.poll() is None:
            _terminate_process(kiwix_proc)

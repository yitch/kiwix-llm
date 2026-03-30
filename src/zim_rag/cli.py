"""Command-line interface for zim-rag."""

from __future__ import annotations

import click
from rich.console import Console

from zim_rag import __version__

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="zim-rag")
def main():
    """zim-rag: Offline RAG system combining Kiwix ZIM archives with local LLMs.

    Ingest ZIM files, query them with natural language, and get cited answers
    from a locally running LLM — fully offline after setup.
    """
    pass


@main.command()
@click.argument("zim_path", type=click.Path(exists=True))
@click.option("--batch-size", type=int, default=None, help="Override batch size from config")
@click.option("--model", type=str, default=None, help="Override embedding model")
def ingest(zim_path: str, batch_size: int | None, model: str | None):
    """Ingest a ZIM file into the knowledge base.

    Extracts articles, chunks them, generates embeddings via Ollama,
    and stores everything in ChromaDB.

    Example: zim-rag ingest ~/zim-files/wikipedia_en_top.zim
    """
    from zim_rag.config import Config
    from zim_rag.ingest import ingest_zim

    config = Config.load()
    if batch_size:
        config.batch_size = batch_size
    if model:
        config.embed_model = model

    ingest_zim(zim_path, config)


@main.command()
@click.argument("question")
@click.option("--top-k", type=int, default=None, help="Number of chunks to retrieve")
@click.option("--model", type=str, default=None, help="Override LLM model")
@click.option("--no-sources", is_flag=True, help="Hide source citations")
def query(question: str, top_k: int | None, model: str | None, no_sources: bool):
    """Ask a question against the ingested knowledge base.

    Retrieves relevant chunks from ChromaDB and generates an answer
    using the local LLM via Ollama.

    Example: zim-rag query "What causes earthquakes?"
    """
    from zim_rag.config import Config
    from zim_rag.query import query_rag

    config = Config.load()
    if top_k:
        config.top_k = top_k
    if model:
        config.llm_model = model

    query_rag(question, config, show_sources=not no_sources)


@main.command()
@click.option("--host", type=str, default=None, help="Host to bind to")
@click.option("--port", type=int, default=None, help="Port for web UI")
@click.option("--kiwix-browse", is_flag=True, help="Also start kiwix-serve for browsing articles")
@click.option("--share", is_flag=True, help="Create a public Gradio share link")
@click.option("--model", type=str, default=None, help="Override LLM model")
def serve(host: str | None, port: int | None, kiwix_browse: bool, share: bool, model: str | None):
    """Start the web UI for interactive querying.

    Launches a Gradio-based chat interface where you can ask questions
    against your ingested knowledge base.

    Use --kiwix-browse to also start kiwix-serve so you can browse
    the original articles in a second browser tab.

    Example: zim-rag serve --kiwix-browse
    """
    from zim_rag.config import Config
    from zim_rag.serve import serve as serve_ui

    config = Config.load()
    if host:
        config.host = host
    if port:
        config.port = port
    if model:
        config.llm_model = model

    serve_ui(config, kiwix_browse=kiwix_browse, share=share)


@main.command()
def info():
    """Show stats about the ingested knowledge base and system status.

    Displays configuration, ChromaDB stats, and available Ollama models.
    """
    from zim_rag.config import Config
    from zim_rag.info import show_info

    config = Config.load()
    show_info(config)


if __name__ == "__main__":
    main()

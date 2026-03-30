"""Show stats about ingested data and system status."""

from __future__ import annotations

import shutil
from pathlib import Path

from rich.console import Console
from rich.table import Table

from zim_rag.config import Config

console = Console()


def get_chromadb_size(path: str) -> str:
    """Get the total size of the ChromaDB directory."""
    db_path = Path(path)
    if not db_path.exists():
        return "0 B"
    total = sum(f.stat().st_size for f in db_path.rglob("*") if f.is_file())
    for unit in ["B", "KB", "MB", "GB"]:
        if total < 1024:
            return f"{total:.1f} {unit}"
        total /= 1024
    return f"{total:.1f} TB"


def get_collection_stats(config: Config) -> dict:
    """Get stats from the ChromaDB collection."""
    import chromadb
    from chromadb.config import Settings

    db_path = Path(config.chromadb_dir)
    if not db_path.exists():
        return {"count": 0, "zim_files": [], "articles": set()}

    client = chromadb.PersistentClient(
        path=config.chromadb_dir,
        settings=Settings(anonymized_telemetry=False),
    )

    try:
        collection = client.get_collection(name=config.collection_name)
    except Exception:
        return {"count": 0, "zim_files": [], "articles": set()}

    count = collection.count()
    if count == 0:
        return {"count": 0, "zim_files": [], "articles": set()}

    # Sample metadata to find unique ZIM files and article titles
    # For large collections, we sample rather than fetching all
    sample_size = min(count, 10000)
    results = collection.peek(limit=sample_size)
    metadatas = results.get("metadatas", [])

    zim_files: set[str] = set()
    articles: set[str] = set()
    for meta in metadatas:
        if meta:
            zim_files.add(meta.get("zim_filename", "unknown"))
            articles.add(meta.get("title", "unknown"))

    return {
        "count": count,
        "zim_files": sorted(zim_files),
        "articles": articles,
    }


def get_ollama_models() -> list[str]:
    """List available Ollama models."""
    try:
        import ollama as ollama_client
        models = ollama_client.list()
        return [m.model for m in models.get("models", models)]
    except Exception:
        return []


def show_info(config: Config | None = None) -> None:
    """Display system information and stats."""
    if config is None:
        config = Config.load()

    console.print()
    console.print("[bold underline]zim-rag System Info[/bold underline]")
    console.print()

    # Config
    table = Table(title="Configuration", show_header=False, padding=(0, 2))
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("Config file", str(config.chromadb_dir).replace("/chromadb", "/config.yaml"))
    table.add_row("ChromaDB dir", config.chromadb_dir)
    table.add_row("LLM model", config.llm_model)
    table.add_row("Embed model", config.embed_model)
    table.add_row("Ollama URL", config.ollama_base_url)
    table.add_row("Chunk size", str(config.chunk_size))
    table.add_row("Top-K", str(config.top_k))
    console.print(table)
    console.print()

    # ChromaDB stats
    stats = get_collection_stats(config)
    db_size = get_chromadb_size(config.chromadb_dir)

    table2 = Table(title="Knowledge Base", show_header=False, padding=(0, 2))
    table2.add_column("Key", style="bold")
    table2.add_column("Value")
    table2.add_row("Total chunks", f"{stats['count']:,}")
    table2.add_row("Unique articles (sampled)", f"{len(stats['articles']):,}")
    table2.add_row("ChromaDB size", db_size)
    table2.add_row("ZIM files ingested", ", ".join(stats["zim_files"]) if stats["zim_files"] else "none")
    console.print(table2)
    console.print()

    # Ollama models
    models = get_ollama_models()
    if models:
        table3 = Table(title="Available Ollama Models")
        table3.add_column("Model", style="cyan")
        for m in models:
            table3.add_row(m)
        console.print(table3)
    else:
        console.print("[yellow]Could not connect to Ollama. Is it running?[/yellow]")

    console.print()

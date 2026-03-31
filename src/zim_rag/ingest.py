"""ZIM file ingestion: extract articles, chunk, embed, and store in ChromaDB."""

from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Generator

from bs4 import BeautifulSoup
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from zim_rag.config import Config

console = Console()


def _zim_priority_key(zim_path: Path) -> tuple[int, str]:
    """Return sort key for ZIM file priority (lower = higher priority).
    
    Priority:
    0. Wikipedia "all maxi" files (broadest coverage)
    1. Wikipedia topic-specific files (medicine, physics, etc.)
    2. All other sources (StackExchange, LibreTexts, etc.)
    
    This ensures high-quality general knowledge is ingested first,
    followed by topic-specific content, then specialized sources.
    """
    name = zim_path.name.lower()
    
    # Priority 0: Wikipedia all maxi (broadest coverage)
    # Pattern: wikipedia_*_all_maxi_*.zim
    if "wikipedia" in name and "_all_maxi" in name:
        return (0, name)
    
    # Priority 1: Wikipedia topic-specific (still high quality)
    # Pattern: wikipedia_*_{topic}_maxi_*.zim (e.g., medicine, physics)
    if "wikipedia" in name and "_maxi" in name:
        return (1, name)
    
    # Priority 2: Everything else (StackExchange, LibreTexts, etc.)
    return (2, name)


def ingest_zim_priority(zim_files: list[Path], config: Config) -> None:
    """Ingest multiple ZIM files in priority order.
    
    Wikipedia "all maxi" files are ingested first for broadest coverage,
    followed by topic-specific Wikipedia files, then other sources.
    """
    # Sort by priority
    sorted_files = sorted(zim_files, key=_zim_priority_key)
    
    if not sorted_files:
        console.print("[yellow]No ZIM files to ingest.[/yellow]")
        return
    
    console.print(f"[bold]Ingesting {len(sorted_files)} ZIM file(s) in priority order:[/bold]")
    for i, zf in enumerate(sorted_files, 1):
        priority = _zim_priority_key(zf)[0]
        priority_label = {0: "★★★", 1: "★★☆", 2: "★☆☆"}[priority]
        console.print(f"  {i}. {priority_label} {zf.name}")
    console.print()
    
    # Ingest in priority order
    for zim_file in sorted_files:
        try:
            ingest_zim(str(zim_file), config)
        except Exception as e:
            console.print(f"[red]Failed to ingest {zim_file.name}: {e}[/red]")
            # Continue with next file


def extract_text_from_html(html: str) -> str:
    """Extract clean text from HTML content."""
    soup = BeautifulSoup(html, "html.parser")
    # Remove script and style elements
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    # Collapse multiple blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def iter_articles(zim_path: str, min_length: int) -> Generator[dict, None, None]:
    """Iterate over text articles in a ZIM file.

    Yields dicts with keys: title, url, text, zim_filename.
    """
    from libzim.reader import Archive  # type: ignore[import-untyped]

    archive = Archive(zim_path)
    zim_filename = Path(zim_path).name
    entry_count = archive.entry_count

    console.print(f"[bold]ZIM file:[/bold] {zim_filename}")
    console.print(f"[bold]Total entries:[/bold] {entry_count:,}")

    MAX_CONTENT_BYTES = 10_000_000  # 10MB per article — skip likely-corrupt entries

    skipped = 0
    for i in range(entry_count):
        try:
            entry = archive._get_entry_by_id(i)
            item = entry.get_item()
        except (KeyError, RuntimeError, OSError):
            skipped += 1
            continue

        # Only process HTML/text content
        mimetype = item.mimetype
        if "html" not in mimetype and "text/plain" not in mimetype:
            continue

        try:
            raw = bytes(item.content)
            if len(raw) > MAX_CONTENT_BYTES:
                skipped += 1
                continue
            content = raw.decode("utf-8", errors="replace")
        except (RuntimeError, OSError):
            skipped += 1
            continue

        if "html" in mimetype:
            text = extract_text_from_html(content)
        else:
            text = content

        if len(text) < min_length:
            continue

        yield {
            "title": entry.title or entry.path,
            "url": entry.path,
            "text": text,
            "zim_filename": zim_filename,
        }

    if skipped > 0:
        console.print(f"[dim]Skipped {skipped:,} non-readable entries[/dim]")


def chunk_article(article: dict, splitter: RecursiveCharacterTextSplitter) -> list[dict]:
    """Split an article into chunks, preserving metadata."""
    chunks = splitter.split_text(article["text"])
    return [
        {
            "text": chunk,
            "metadata": {
                "title": article["title"],
                "url": article["url"],
                "zim_filename": article["zim_filename"],
                "chunk_index": i,
            },
        }
        for i, chunk in enumerate(chunks)
    ]


def make_chunk_id(metadata: dict, chunk_text: str) -> str:
    """Create a deterministic ID for a chunk to enable deduplication."""
    key = f"{metadata['zim_filename']}:{metadata['url']}:{metadata['chunk_index']}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def ingest_zim(zim_path: str, config: Config | None = None) -> None:
    """Ingest a ZIM file into ChromaDB.

    Extracts articles, chunks them, generates embeddings via Ollama,
    and stores everything in a persistent ChromaDB collection.
    """
    import chromadb
    from chromadb.config import Settings
    from langchain_ollama import OllamaEmbeddings

    if config is None:
        config = Config.load()
    config.ensure_dirs()

    zim_path_resolved = str(Path(zim_path).resolve())
    if not Path(zim_path_resolved).exists():
        console.print(f"[red]Error:[/red] ZIM file not found: {zim_path}")
        raise SystemExit(1)

    # Initialize embeddings
    console.print(f"[bold]Embedding model:[/bold] {config.embed_model}")
    console.print(f"[bold]Ollama URL:[/bold] {config.ollama_base_url}")

    try:
        embeddings = OllamaEmbeddings(
            model=config.embed_model,
            base_url=config.ollama_base_url,
        )
        # Quick connectivity test
        embeddings.embed_query("test")
    except Exception as e:
        console.print(f"[red]Error connecting to Ollama:[/red] {e}")
        console.print("[yellow]Make sure Ollama is running: ollama serve[/yellow]")
        console.print(f"[yellow]Make sure the model is pulled: ollama pull {config.embed_model}[/yellow]")
        raise SystemExit(1)

    # Initialize ChromaDB
    client = chromadb.PersistentClient(
        path=config.chromadb_dir,
        settings=Settings(anonymized_telemetry=False),
    )
    collection = client.get_or_create_collection(
        name=config.collection_name,
        metadata={"hnsw:space": "cosine"},
    )

    console.print(f"[bold]ChromaDB:[/bold] {config.chromadb_dir}")
    console.print(f"[bold]Existing chunks:[/bold] {collection.count():,}")

    # Set up text splitter
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        length_function=len,  # character-based; token-based is slower but more accurate
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    # Process articles in batches
    batch_texts: list[str] = []
    batch_metadatas: list[dict] = []
    batch_ids: list[str] = []
    articles_processed = 0
    chunks_total = 0
    chunks_failed = 0
    start_time = time.time()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed:,} articles"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Ingesting...", total=None)

        for article in iter_articles(zim_path_resolved, config.min_article_length):
            chunks = chunk_article(article, splitter)

            for chunk in chunks:
                chunk_id = make_chunk_id(chunk["metadata"], chunk["text"])
                batch_texts.append(chunk["text"])
                batch_metadatas.append(chunk["metadata"])
                batch_ids.append(chunk_id)

            articles_processed += 1
            chunks_total += len(chunks)
            progress.update(task, completed=articles_processed)

            # Flush batch
            if len(batch_texts) >= config.batch_size:
                failed = _flush_batch(collection, embeddings, batch_ids, batch_texts, batch_metadatas)
                chunks_failed += failed
                batch_texts.clear()
                batch_metadatas.clear()
                batch_ids.clear()

        # Final batch
        if batch_texts:
            failed = _flush_batch(collection, embeddings, batch_ids, batch_texts, batch_metadatas)
            chunks_failed += failed

    elapsed = time.time() - start_time
    console.print()
    console.print(f"[green bold]Ingestion complete![/green bold]")
    console.print(f"  Articles processed: {articles_processed:,}")
    console.print(f"  Chunks created:     {chunks_total:,}")
    if chunks_failed > 0:
        console.print(f"  [red]Chunks failed:      {chunks_failed:,}[/red]")
    console.print(f"  Total in ChromaDB:  {collection.count():,}")
    console.print(f"  Time elapsed:       {elapsed:.1f}s")


def _flush_batch(
    collection: "chromadb.Collection",
    embeddings: "OllamaEmbeddings",
    ids: list[str],
    texts: list[str],
    metadatas: list[dict],
) -> int:
    """Embed and upsert a batch of chunks into ChromaDB.

    Returns the number of chunks that failed to embed.
    """
    failed = 0
    try:
        vectors = embeddings.embed_documents(texts)
        collection.upsert(
            ids=ids,
            embeddings=vectors,
            documents=texts,
            metadatas=metadatas,
        )
    except Exception as e:
        console.print(f"[red]Error embedding batch:[/red] {e}")
        console.print("[yellow]Retrying batch one-by-one...[/yellow]")
        for i in range(len(ids)):
            try:
                vec = embeddings.embed_documents([texts[i]])
                collection.upsert(
                    ids=[ids[i]],
                    embeddings=vec,
                    documents=[texts[i]],
                    metadatas=[metadatas[i]],
                )
            except Exception as inner_e:
                failed += 1
                console.print(f"[red]Skipping chunk {ids[i]}:[/red] {inner_e}")
    return failed

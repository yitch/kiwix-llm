"""Query the RAG pipeline: retrieve chunks and generate answers."""

from __future__ import annotations

import logging

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from zim_rag.config import Config

console = Console()
logger = logging.getLogger(__name__)


class NoIngestedDataError(Exception):
    """Raised when no data has been ingested yet."""
    pass


def retrieve_chunks(question: str, config: Config) -> list[dict]:
    """Retrieve the top-k most relevant chunks from ChromaDB.

    Raises NoIngestedDataError if no data has been ingested.
    """
    import chromadb
    from chromadb.config import Settings
    from langchain_ollama import OllamaEmbeddings

    embeddings = OllamaEmbeddings(
        model=config.embed_model,
        base_url=config.ollama_base_url,
    )

    client = chromadb.PersistentClient(
        path=config.chromadb_dir,
        settings=Settings(anonymized_telemetry=False),
    )

    try:
        collection = client.get_collection(name=config.collection_name)
    except Exception:
        raise NoIngestedDataError("No ingested data found. Run 'zim-rag ingest' first.")

    if collection.count() == 0:
        raise NoIngestedDataError("Collection is empty. Run 'zim-rag ingest' first.")

    query_embedding = embeddings.embed_query(question)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=config.top_k,
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    for i in range(len(results["ids"][0])):
        chunks.append({
            "text": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "distance": results["distances"][0][i],
        })
    return chunks


def retrieve_chunks_diverse(question: str, config: Config) -> list[dict]:
    """Retrieve chunks with diversity across ZIM sources.
    
    Uses Maximal Marginal Relevance (MMR)-like approach to ensure
    results come from multiple ZIM files, not just the top-k similar chunks
    from a single source.
    
    Algorithm:
    1. Fetch 3x top_k candidates (more candidates = more diversity options)
    2. Select chunks round-robin from different ZIM sources
    3. Prioritize by relevance within each source
    4. Limit to max_sources unique ZIM files
    5. Continue until we have top_k chunks from diverse sources
    """
    import chromadb
    from chromadb.config import Settings
    from langchain_ollama import OllamaEmbeddings
    from collections import defaultdict

    embeddings = OllamaEmbeddings(
        model=config.embed_model,
        base_url=config.ollama_base_url,
    )

    client = chromadb.PersistentClient(
        path=config.chromadb_dir,
        settings=Settings(anonymized_telemetry=False),
    )

    try:
        collection = client.get_collection(name=config.collection_name)
    except Exception:
        raise NoIngestedDataError("No ingested data found. Run 'zim-rag ingest' first.")

    if collection.count() == 0:
        raise NoIngestedDataError("Collection is empty. Run 'zim-rag ingest' first.")

    query_embedding = embeddings.embed_query(question)

    # Fetch more candidates for diversity selection (3x top_k, capped at 200)
    n_candidates = min(config.top_k * 3, 200)
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_candidates,
        include=["documents", "metadatas", "distances"],
    )

    # Build list of all candidate chunks
    all_candidates = []
    for i in range(len(results["ids"][0])):
        all_candidates.append({
            "text": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "distance": results["distances"][0][i],
        })

    if not all_candidates:
        return []

    # Group candidates by ZIM file (source)
    chunks_by_zim = defaultdict(list)
    for chunk in all_candidates:
        zim = chunk["metadata"].get("zim_filename", "unknown")
        chunks_by_zim[zim].append(chunk)

    # Sort each group's chunks by relevance (distance ascending)
    for zim in chunks_by_zim:
        chunks_by_zim[zim].sort(key=lambda x: x["distance"])

    # Sort ZIM sources by their best chunk's relevance (best first)
    zim_sources = sorted(
        chunks_by_zim.keys(),
        key=lambda zim: chunks_by_zim[zim][0]["distance"]
    )
    
    # Limit to max_sources ZIM files for diversity
    if len(zim_sources) > config.max_sources:
        zim_sources = zim_sources[:config.max_sources]

    # Calculate max chunks per source to ensure fairness
    # Each source gets at most ceil(top_k / num_sources) chunks
    import math
    max_per_source = math.ceil(config.top_k / len(zim_sources))

    zim_indices = {zim: 0 for zim in zim_sources}
    zim_counts = {zim: 0 for zim in zim_sources}
    
    # Round-robin selection for diversity
    selected = []
    
    # Continue until we have top_k chunks or exhaust candidates
    while len(selected) < config.top_k:
        made_progress = False
        
        for zim in zim_sources:
            idx = zim_indices[zim]
            # Respect per-source cap
            if idx < len(chunks_by_zim[zim]) and zim_counts[zim] < max_per_source:
                selected.append(chunks_by_zim[zim][idx])
                zim_indices[zim] = idx + 1
                zim_counts[zim] += 1
                made_progress = True
                
                if len(selected) >= config.top_k:
                    break
        
        if not made_progress:
            # No more candidates from any source (or all at cap)
            break

    # Sort final selection by relevance for coherent context
    selected.sort(key=lambda x: x["distance"])
    
    return selected


def format_context(chunks: list[dict]) -> str:
    """Format retrieved chunks into a context string for the LLM."""
    parts = []
    for i, chunk in enumerate(chunks, 1):
        meta = chunk["metadata"]
        title = meta.get("title", "Unknown")
        source = meta.get("zim_filename", "Unknown")
        parts.append(
            f"--- Source {i}: \"{title}\" (from {source}) ---\n"
            f"{chunk['text']}\n"
        )
    return "\n".join(parts)


def query_rag(question: str, config: Config | None = None, show_sources: bool = True) -> str:
    """Run a full RAG query: retrieve context, then generate an answer.

    Returns the LLM's answer as a string.
    """
    import ollama as ollama_client

    if config is None:
        config = Config.load()

    # Retrieve relevant chunks with diversity across ZIM sources
    try:
        chunks = retrieve_chunks_diverse(question, config)
    except NoIngestedDataError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1)

    if not chunks:
        return "No relevant information found in the knowledge base."

    # Build the prompt
    context = format_context(chunks)
    user_prompt = (
        f"Context from reference articles:\n\n{context}\n\n"
        f"Question: {question}\n\n"
        f"Answer the question using only the context above. Cite the source article titles."
    )

    # Call Ollama
    try:
        response = ollama_client.chat(
            model=config.llm_model,
            messages=[
                {"role": "system", "content": config.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            options={"num_ctx": 4096},
        )
        answer = response["message"]["content"]
    except Exception as e:
        console.print(f"[red]Error calling Ollama:[/red] {e}")
        console.print(f"[yellow]Make sure the model is available: ollama pull {config.llm_model}[/yellow]")
        raise SystemExit(1)

    # Display results
    if show_sources:
        console.print()
        console.print(Panel(Markdown(answer), title="Answer", border_style="green"))
        console.print()
        console.print("[bold]Sources:[/bold]")
        seen_titles: set[str] = set()
        for chunk in chunks:
            title = chunk["metadata"].get("title", "Unknown")
            source = chunk["metadata"].get("zim_filename", "")
            dist = chunk["distance"]
            if title not in seen_titles:
                seen_titles.add(title)
                console.print(f"  • {title} [dim]({source}, distance: {dist:.4f})[/dim]")
        console.print()

    return answer


def query_rag_simple(question: str, config: Config) -> tuple[str, list[dict]]:
    """Query without printing — returns (answer, chunks) for use by the web UI."""
    import ollama as ollama_client

    try:
        # Use diverse retrieval to ensure sources from multiple ZIM files
        chunks = retrieve_chunks_diverse(question, config)
    except NoIngestedDataError:
        return (
            "📚 **No knowledge base found.**\n\n"
            "Please ingest ZIM files first:\n\n"
            "1. Click **📂 ZIM Folder** to select your ZIM files folder\n"
            "2. Click **🚀 Ingest** to process the files\n\n"
            "Or run from command line:\n"
            "```\nzim-rag ingest ~/zim-files/your-file.zim\n```"
        ), []

    if not chunks:
        return "No relevant information found in the knowledge base.", []

    context = format_context(chunks)
    user_prompt = (
        f"Context from reference articles:\n\n{context}\n\n"
        f"Question: {question}\n\n"
        f"Answer the question using only the context above. Cite the source article titles."
    )

    try:
        response = ollama_client.chat(
            model=config.llm_model,
            messages=[
                {"role": "system", "content": config.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            options={"num_ctx": 4096},
        )
        answer = response["message"]["content"]
    except Exception as e:
        logger.error("Ollama query failed: %s", e)
        return "Sorry, there was an error generating the answer. Check that Ollama is running.", chunks

    return answer, chunks

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

    # Retrieve relevant chunks
    try:
        chunks = retrieve_chunks(question, config)
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
        chunks = retrieve_chunks(question, config)
    except NoIngestedDataError:
        return (
            "No knowledge base found. Please ingest a ZIM file first:\n\n"
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

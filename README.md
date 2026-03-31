# zim-rag

Offline knowledge assistant that combines [Kiwix](https://kiwix.org) ZIM archives with a local LLM for Retrieval-Augmented Generation (RAG). Ask natural language questions against Wikipedia, WikiMed, Stack Exchange, and more — fully offline after setup.

Built for **macOS on Apple Silicon** (Mac Mini M4, MacBook Pro M-series, etc.). Uses Metal acceleration via Ollama for fast local inference.

## How it works

```
ZIM file → extract articles → chunk text → embed (nomic-embed-text)
                                                 ↓
                                            ChromaDB (local vector store)
                                                 ↓
    Question → embed → retrieve top-k chunks → LLM prompt → answer with citations
```

- **Kiwix ZIM files** contain offline snapshots of Wikipedia, Stack Exchange, and other reference sites
- **Ollama** runs the LLM and embedding model locally on your Mac's GPU (Metal)
- **ChromaDB** stores embeddings persistently on disk
- **Gradio** provides a simple web chat UI

## One-line install

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/yitch/kiwix-llm/main/install.sh)"
```

This clones the repo, installs all dependencies, pulls the right LLM for your RAM, and downloads a starter Wikipedia ZIM. Then just:

```bash
cd ~/kiwix-llm && source .venv/bin/activate
ollama serve &                                          # start Ollama if not running
zim-rag ingest ~/zim-files/wikipedia_en_top_maxi_2024-10.zim
zim-rag query "What causes earthquakes?"
```

## Manual setup

```bash
# 1. Clone and set up
git clone https://github.com/yitch/kiwix-llm.git
cd kiwix-llm
chmod +x setup.sh download-zims.sh install.sh
./setup.sh

# 2. Activate the virtualenv
source .venv/bin/activate

# 3. Download starter ZIM files (~2GB for Wikipedia top articles)
./download-zims.sh wikipedia

# 4. Ingest into the knowledge base
zim-rag ingest ~/zim-files/wikipedia_en_top_maxi_2024-10.zim

# 5. Ask a question
zim-rag query "What causes earthquakes?"

# 6. Or use the web UI
zim-rag serve
```

## Commands

### `zim-rag ingest <path-to-zim>`

Extract articles from a ZIM file, chunk them, generate embeddings, and store in ChromaDB.

```bash
zim-rag ingest ~/zim-files/wikipedia_en_top_maxi_2024-10.zim
zim-rag ingest ~/zim-files/wikipedia_en_medicine_maxi_2024-10.zim

# Override batch size for large ZIMs
zim-rag ingest --batch-size 50 ~/zim-files/huge-file.zim
```

### `zim-rag query "question"`

Retrieve relevant chunks and generate an answer with source citations.

```bash
zim-rag query "What is photosynthesis?"
zim-rag query --top-k 10 "Explain TCP/IP"
zim-rag query --model mistral-small "How does insulin work?"
zim-rag query --no-sources "What is the capital of France?"
```

### `zim-rag serve`

Start a Gradio web UI for interactive querying.

```bash
zim-rag serve                          # Default: http://localhost:7860
zim-rag serve --port 8080              # Custom port
zim-rag serve --kiwix-browse           # Also starts kiwix-serve for article browsing
zim-rag serve --model mistral-small    # Override LLM model
```

The `--kiwix-browse` flag starts `kiwix-serve` alongside the chat UI so you can browse original ZIM articles in a second browser tab (default: http://localhost:8888).

### `zim-rag info`

Show stats about your knowledge base and system.

```bash
zim-rag info
```

Displays: chunk count, ingested ZIM files, ChromaDB size, config values, and available Ollama models.

## Configuration

Config file: `~/.zim-rag/config.yaml` (created automatically by `setup.sh`).

See [`config.example.yaml`](config.example.yaml) for all options. Key settings:

| Setting | Default | Description |
|---------|---------|-------------|
| `ollama.llm_model` | `qwen3:8b` | LLM for answering (auto-detected by RAM during setup) |
| `ollama.embed_model` | `nomic-embed-text` | Embedding model (change requires re-ingestion) |
| `chunking.chunk_size` | `500` | Characters per chunk |
| `query.top_k` | `5` | Number of chunks to retrieve |

### Model recommendations by RAM

| RAM | Recommended LLM | Notes |
|-----|-----------------|-------|
| 16GB | `qwen3:8b` or `llama3.1:8b` | Good balance of speed and quality |
| 24GB | `mistral-small` or `qwen3:14b` | Better reasoning |
| 32GB+ | `qwen3:32b` or `llama3.1:70b-q4` | Best quality, slower |

## Architecture

```
~/.zim-rag/
├── config.yaml          # Configuration
└── chromadb/            # Persistent vector database

~/zim-files/             # Downloaded ZIM files
```

**Dependencies:**
- [Ollama](https://ollama.com) — local LLM inference with Metal acceleration
- [kiwix-tools](https://github.com/kiwix/kiwix-tools) — ZIM file browser
- [ChromaDB](https://www.trychroma.com) — vector database
- [python-libzim](https://github.com/openzim/python-libzim) — read ZIM files directly
- [LangChain](https://langchain.com) — text splitting and embeddings integration
- [Gradio](https://gradio.app) — web UI

## Troubleshooting

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for solutions to common issues.

**Quick fixes for the most common problems:**

- **"Connection refused" from Ollama** — Run `ollama serve` in a terminal
- **"Model not found"** — Run `ollama pull <model-name>`
- **Ingestion is slow** — Reduce `batch_size` in config; for huge ZIMs, expect hours
- **"No module named libzim"** — `pip install libzim` (requires the C library; `setup.sh` handles this)
- **ChromaDB errors after upgrade** — Delete `~/.zim-rag/chromadb/` and re-ingest

## Contributing

Contributions welcome! Some ideas:

- Linux support (adapt `setup.sh`)
- Docker Compose setup
- PDF/EPUB ingestion alongside ZIM
- Better chunking strategies (semantic chunking)
- Hybrid search (BM25 + vector)
- Open WebUI integration
- launchd plist for running as a background service

## License

MIT

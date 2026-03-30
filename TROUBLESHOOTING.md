# Troubleshooting

Common issues and solutions for zim-rag.

## Setup issues

### Homebrew not found

```
Error: brew: command not found
```

Install Homebrew manually:
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

On Apple Silicon, add to your shell profile:
```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
source ~/.zprofile
```

### Python version too old

```
Error: Python 3.11+ required
```

Install a newer Python:
```bash
brew install python@3.12
```

Make sure it's on your PATH:
```bash
python3.12 --version
```

### libzim installation fails

If `pip install libzim` fails with compilation errors:

```bash
# Make sure you have the system library
brew install libzim

# Then install the Python bindings
pip install libzim
```

If it still fails, try installing from conda-forge:
```bash
conda install -c conda-forge python-libzim
```

## Ollama issues

### "Connection refused" or "Cannot connect to Ollama"

Ollama isn't running. Start it:
```bash
ollama serve
```

Or check if it's running:
```bash
curl http://localhost:11434/api/tags
```

If you see Ollama running but on a different port, update `~/.zim-rag/config.yaml`:
```yaml
ollama:
  base_url: "http://localhost:YOUR_PORT"
```

### "Model not found"

Pull the required models:
```bash
ollama pull nomic-embed-text   # Required for embeddings
ollama pull qwen3:8b           # Or your chosen LLM
```

List available models:
```bash
ollama list
```

### Ollama is slow

- Check Activity Monitor — Ollama should be using GPU (Metal). If it shows high CPU but low GPU, there may be a compatibility issue
- Try a smaller model: `qwen3:4b` instead of `qwen3:8b`
- Close other GPU-intensive applications
- Check your model fits in RAM: 8B models need ~8GB free, 14B models need ~12GB free

### "Out of memory" during inference

Your model is too large for your RAM:
```bash
# Switch to a smaller model
ollama pull qwen3:4b
```

Update `~/.zim-rag/config.yaml`:
```yaml
ollama:
  llm_model: "qwen3:4b"
```

## Ingestion issues

### Ingestion is very slow

This is normal for large ZIM files. Wikipedia top articles (~2GB ZIM) takes roughly 30-60 minutes depending on your hardware.

Tips:
- Reduce batch size if you're running low on memory:
  ```bash
  zim-rag ingest --batch-size 25 file.zim
  ```
- The embedding step (calling Ollama) is the bottleneck, not file reading
- Progress is saved — if you interrupt and restart, existing chunks won't be re-embedded (deduplication by chunk ID)

### "Error embedding batch" messages

Usually a transient Ollama issue. The system retries one-by-one automatically. If it persists:
1. Check Ollama logs: `cat ~/.ollama/logs/server.log`
2. Restart Ollama: `pkill ollama && ollama serve`
3. Re-run the ingest command (it deduplicates, so it won't redo work)

### ZIM file not found

Make sure you're using the full path:
```bash
# This works
zim-rag ingest ~/zim-files/wikipedia_en_top_maxi_2024-10.zim

# This might not (relative paths)
zim-rag ingest wikipedia_en_top_maxi_2024-10.zim
```

### "No articles found" or very few chunks

Some ZIM files have different internal structures. Check:
```bash
# See what's in the ZIM
python3 -c "
from libzim.reader import Archive
a = Archive('your-file.zim')
print(f'Entries: {a.entry_count}')
for i in range(min(10, a.entry_count)):
    e = a._get_entry_by_id(i)
    print(f'  {e.path} ({e.get_item().mimetype})')
"
```

If articles are too short, lower the minimum length:
```yaml
ingest:
  min_article_length: 50  # default is 100
```

## Query issues

### "No ingested data found"

You need to ingest at least one ZIM file first:
```bash
zim-rag ingest ~/zim-files/some-file.zim
```

Check what's ingested:
```bash
zim-rag info
```

### Bad or irrelevant answers

- Increase `top_k` to retrieve more context:
  ```bash
  zim-rag query --top-k 10 "your question"
  ```
- Try a different/larger LLM model:
  ```bash
  zim-rag query --model mistral-small "your question"
  ```
- Make sure you've ingested a ZIM file that contains relevant content
- Questions work best when they match the domain of your ingested content

### Answers are slow

The LLM generation step depends on model size and your hardware:
- 8B models: ~20-40 tokens/sec on M4
- 14B models: ~10-20 tokens/sec on M4
- Try a smaller model if speed matters more than quality

## ChromaDB issues

### "ChromaDB version mismatch" or strange errors after upgrade

Delete and re-ingest:
```bash
rm -rf ~/.zim-rag/chromadb/
zim-rag ingest ~/zim-files/your-file.zim
```

### ChromaDB directory is huge

Vector embeddings take space. Rough estimates:
- ~1KB per chunk (embedding + metadata)
- 100K chunks ≈ 100-200MB
- Full Wikipedia could be 10GB+

To reduce size, increase `chunk_size` in config (fewer, larger chunks).

## Web UI issues

### Gradio won't start

```
Error: Port 7860 already in use
```

Use a different port:
```bash
zim-rag serve --port 8080
```

Or find and kill the existing process:
```bash
lsof -i :7860
kill <PID>
```

### kiwix-serve not starting with --kiwix-browse

Make sure kiwix-tools is installed:
```bash
brew install kiwix-tools
which kiwix-serve
```

And that ZIM files exist in `~/zim-files/`:
```bash
ls ~/zim-files/*.zim
```

## Download issues

### ZIM download URLs are broken

ZIM file URLs change as new versions are released. If `download-zims.sh` fails:

1. Browse https://download.kiwix.org/zim/ to find current filenames
2. Update the URLs in `download-zims.sh`
3. Or use the [Kiwix library](https://library.kiwix.org) to find downloads

### Download is interrupted

Re-run `download-zims.sh` — it skips already-downloaded files. For partial downloads, delete the incomplete file first:
```bash
rm ~/zim-files/partial-file.zim
./download-zims.sh wikipedia
```

## Getting help

1. Check the [GitHub Issues](https://github.com/yitch/kiwix-llm/issues)
2. Open a new issue with:
   - Your macOS version and chip (M1/M2/M3/M4)
   - RAM amount
   - Output of `zim-rag info`
   - The full error message

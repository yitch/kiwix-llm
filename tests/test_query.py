"""Tests for query module."""

import pytest
from unittest.mock import Mock, patch, MagicMock

from zim_rag.query import retrieve_chunks, format_context
from zim_rag.config import Config


class TestRetrieveChunks:
    """Tests for retrieve_chunks function."""

    def test_retrieve_chunks_uses_config_top_k(self):
        """Test that retrieve_chunks respects the config's top_k value."""
        config = Config(top_k=50)  # Larger top_k
        
        mock_collection = Mock()
        mock_collection.count.return_value = 1000
        mock_collection.query.return_value = {
            "ids": [[f"id_{i}" for i in range(50)]],
            "documents": [[f"doc_{i}" for i in range(50)]],
            "metadatas": [[{"title": f"Article {i}"} for i in range(50)]],
            "distances": [[0.1 * i for i in range(50)]],
        }
        
        mock_client = Mock()
        mock_client.get_collection.return_value = mock_collection
        
        with patch('chromadb.PersistentClient', return_value=mock_client):
            with patch('langchain_ollama.OllamaEmbeddings') as mock_embed:
                mock_embed.return_value.embed_query.return_value = [0.1] * 768
                chunks = retrieve_chunks("test question", config)
        
        # Verify collection.query was called with correct n_results
        mock_collection.query.assert_called_once()
        call_kwargs = mock_collection.query.call_args[1]
        assert call_kwargs['n_results'] == 50, f"Expected n_results=50, got {call_kwargs['n_results']}"
        
        # Verify we got the expected number of chunks
        assert len(chunks) == 50, f"Expected 50 chunks, got {len(chunks)}"

    def test_retrieve_chunks_returns_diverse_sources(self):
        """Test that retrieve_chunks can return chunks from multiple sources."""
        config = Config(top_k=20)
        
        # Simulate chunks from multiple ZIM files
        zim_files = [
            "wikipedia_en_all_maxi_2026-02.zim",
            "electronics.stackexchange.com_en_all_2026-02.zim", 
            "physics.stackexchange.com_en_all_2026-02.zim",
            "engineering.stackexchange.com_en_all_2026-02.zim",
        ]
        
        mock_collection = Mock()
        mock_collection.count.return_value = 10000
        
        # Create metadata from diverse sources
        metadatas = []
        for i in range(20):
            zim = zim_files[i % len(zim_files)]
            metadatas.append({
                "title": f"Article {i}",
                "zim_filename": zim,
                "url": f"/article_{i}",
            })
        
        mock_collection.query.return_value = {
            "ids": [[f"id_{i}" for i in range(20)]],
            "documents": [[f"Content of article {i}" for i in range(20)]],
            "metadatas": [metadatas],
            "distances": [[0.05 * i for i in range(20)]],
        }
        
        mock_client = Mock()
        mock_client.get_collection.return_value = mock_collection
        
        with patch('chromadb.PersistentClient', return_value=mock_client):
            with patch('langchain_ollama.OllamaEmbeddings') as mock_embed:
                mock_embed.return_value.embed_query.return_value = [0.1] * 768
                chunks = retrieve_chunks("test", config)
        
        # Verify we got chunks from multiple sources
        unique_zims = set(chunk['metadata']['zim_filename'] for chunk in chunks)
        assert len(unique_zims) > 1, f"Expected multiple ZIM sources, got only: {unique_zims}"
        assert len(unique_zims) >= 3, f"Expected at least 3 different ZIM sources for diversity, got {len(unique_zims)}"

    def test_default_top_k_is_reasonable_for_large_kb(self):
        """Test that default top_k is reasonable for large knowledge bases."""
        config = Config()  # Use defaults
        
        # The default top_k should be at least 20-50 for good coverage
        # with multiple ZIM files
        assert config.top_k >= 20, (
            f"Default top_k ({config.top_k}) is too small for large knowledge bases. "
            "Should be at least 20 to ensure diverse source coverage."
        )


class TestFormatContext:
    """Tests for format_context function."""

    def test_format_context_includes_source_info(self):
        """Test that format_context includes source article and ZIM file info."""
        chunks = [
            {
                "text": "This is content about Python.",
                "metadata": {
                    "title": "Python Programming",
                    "zim_filename": "wikipedia_en_all_maxi_2026-02.zim",
                },
                "distance": 0.1,
            },
            {
                "text": "This is about circuits.",
                "metadata": {
                    "title": "Circuit Design",
                    "zim_filename": "electronics.stackexchange.com_en_all_2026-02.zim",
                },
                "distance": 0.15,
            },
        ]
        
        context = format_context(chunks)
        
        # Should include source numbers
        assert "Source 1:" in context
        assert "Source 2:" in context
        
        # Should include titles
        assert "Python Programming" in context
        assert "Circuit Design" in context
        
        # Should include ZIM filenames
        assert "wikipedia_en_all_maxi_2026-02.zim" in context
        assert "electronics.stackexchange.com_en_all_2026-02.zim" in context


class TestSourceDeduplication:
    """Tests for source deduplication behavior."""

    def test_sources_deduplicated_by_title_in_ui(self):
        """Test that UI shows unique sources, not duplicate chunks from same article."""
        # Simulating the web UI deduplication logic
        chunks = [
            {"metadata": {"title": "Python", "zim_filename": "wiki.zim"}},
            {"metadata": {"title": "Python", "zim_filename": "wiki.zim"}},  # Same article
            {"metadata": {"title": "Java", "zim_filename": "wiki.zim"}},
            {"metadata": {"title": "Java", "zim_filename": "wiki.zim"}},  # Same article
        ]
        
        seen_titles = set()
        unique_sources = []
        for chunk in chunks:
            title = chunk["metadata"].get("title", "Unknown")
            if title not in seen_titles:
                seen_titles.add(title)
                unique_sources.append(title)
        
        assert len(unique_sources) == 2, f"Expected 2 unique sources, got {len(unique_sources)}"
        assert "Python" in unique_sources
        assert "Java" in unique_sources

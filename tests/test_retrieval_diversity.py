"""Functional tests for retrieval diversity across multiple ZIM sources."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import numpy as np

from zim_rag.query import retrieve_chunks_diverse, format_context
from zim_rag.config import Config


class TestDiverseRetrieval:
    """Tests that retrieval returns diverse sources from multiple ZIM files."""

    def test_retrieval_returns_chunks_from_multiple_zim_files(self):
        """Critical test: Query should return sources from multiple ZIMs, not just one."""
        config = Config(top_k=50, max_sources=20)
        
        # Simulate chunks from 5 different ZIM files
        zim_files = [
            "wikipedia_en_all_maxi_2026-02.zim",
            "electronics.stackexchange.com_en_all_2026-02.zim",
            "physics.stackexchange.com_en_all_2026-02.zim",
            "engineering.stackexchange.com_en_all_2026-02.zim",
            "libretexts.org_en_math_2026-01.zim",
        ]
        
        # Create 50 mock chunks (10 from each ZIM)
        all_chunks = []
        for zim_idx, zim in enumerate(zim_files):
            for i in range(10):
                all_chunks.append({
                    "id": f"chunk_{zim_idx}_{i}",
                    "text": f"Content about topic {i} from {zim}",
                    "metadata": {
                        "title": f"Article {zim_idx}-{i}",
                        "zim_filename": zim,
                        "url": f"/article_{zim_idx}_{i}",
                    },
                    # Simulate similarity scores - some from each ZIM are relevant
                    "distance": 0.1 + (i * 0.01) + (zim_idx * 0.001)
                })
        
        mock_collection = Mock()
        mock_collection.count.return_value = len(all_chunks)
        
        # Return all chunks sorted by distance
        sorted_chunks = sorted(all_chunks, key=lambda x: x["distance"])
        mock_collection.query.return_value = {
            "ids": [[c["id"] for c in sorted_chunks]],
            "documents": [[c["text"] for c in sorted_chunks]],
            "metadatas": [[c["metadata"] for c in sorted_chunks]],
            "distances": [[c["distance"] for c in sorted_chunks]],
        }
        
        mock_client = Mock()
        mock_client.get_collection.return_value = mock_collection
        
        with patch('chromadb.PersistentClient', return_value=mock_client):
            with patch('langchain_ollama.OllamaEmbeddings') as mock_embed:
                mock_embed.return_value.embed_query.return_value = [0.1] * 768
                
                # Call the new diverse retrieval function
                chunks = retrieve_chunks_diverse("How does a CPU work?", config)
        
        # CRITICAL ASSERTION: Must have chunks from at least 3 different ZIM files
        unique_zims = set(chunk['metadata']['zim_filename'] for chunk in chunks)
        assert len(unique_zims) >= 3, (
            f"Retrieval returned chunks from only {len(unique_zims)} ZIM file(s): {unique_zims}. "
            f"Expected at least 3 different ZIM sources for diversity. "
            f"Total chunks returned: {len(chunks)}"
        )
        
        # Should have Wikipedia for CPU info
        wikipedia_present = any(
            'wikipedia' in chunk['metadata']['zim_filename'].lower()
            for chunk in chunks
        )
        assert wikipedia_present, (
            "Wikipedia source not found in results. For a query about 'How does a CPU work?', "
            "Wikipedia should be a primary source."
        )

    def test_no_single_zim_dominates_results(self):
        """Test that no single ZIM file provides more than 50% of results."""
        config = Config(top_k=50, max_sources=20)
        
        # Simulate scenario where electronics.SE has many "relevant" chunks
        # but we still want diversity
        all_chunks = []
        
        # Electronics.SE has 30 "very relevant" chunks (low distance)
        for i in range(30):
            all_chunks.append({
                "id": f"elec_{i}",
                "text": f"Electronics content {i}",
                "metadata": {
                    "title": f"Electronics Article {i}",
                    "zim_filename": "electronics.stackexchange.com_en_all_2026-02.zim",
                },
                "distance": 0.05 + (i * 0.001)
            })
        
        # Other sources have 20 chunks with slightly higher distance
        other_sources = [
            "wikipedia_en_all_maxi_2026-02.zim",
            "physics.stackexchange.com_en_all_2026-02.zim",
        ]
        for src_idx, src in enumerate(other_sources):
            for i in range(10):
                all_chunks.append({
                    "id": f"other_{src_idx}_{i}",
                    "text": f"Content from {src}",
                    "metadata": {
                        "title": f"Article {src_idx}-{i}",
                        "zim_filename": src,
                    },
                    "distance": 0.1 + (i * 0.01)  # Higher distance = less similar
                })
        
        mock_collection = Mock()
        mock_collection.count.return_value = len(all_chunks)
        
        sorted_chunks = sorted(all_chunks, key=lambda x: x["distance"])
        mock_collection.query.return_value = {
            "ids": [[c["id"] for c in sorted_chunks]],
            "documents": [[c["text"] for c in sorted_chunks]],
            "metadatas": [[c["metadata"] for c in sorted_chunks]],
            "distances": [[c["distance"] for c in sorted_chunks]],
        }
        
        mock_client = Mock()
        mock_client.get_collection.return_value = mock_collection
        
        with patch('chromadb.PersistentClient', return_value=mock_client):
            with patch('langchain_ollama.OllamaEmbeddings') as mock_embed:
                mock_embed.return_value.embed_query.return_value = [0.1] * 768
                chunks = retrieve_chunks_diverse("test query", config)
        
        # Count chunks per ZIM
        zim_counts = {}
        for chunk in chunks:
            zim = chunk['metadata']['zim_filename']
            zim_counts[zim] = zim_counts.get(zim, 0) + 1
        
        # No single ZIM should dominate (>50% of results)
        for zim, count in zim_counts.items():
            percentage = count / len(chunks)
            assert percentage <= 0.6, (
                f"ZIM file '{zim}' provides {percentage:.1%} of results ({count}/{len(chunks)}). "
                f"No single source should dominate. Expected max 60% per source."
            )

    def test_diverse_retrieval_respects_max_sources(self):
        """Test that diverse retrieval respects max_sources limit."""
        config = Config(top_k=50, max_sources=5)
        
        # Create chunks from many ZIMs
        all_chunks = []
        for zim_idx in range(10):  # 10 different ZIMs
            for i in range(5):  # 5 chunks each
                all_chunks.append({
                    "id": f"chunk_{zim_idx}_{i}",
                    "text": f"Content {i}",
                    "metadata": {
                        "title": f"Article {zim_idx}-{i}",
                        "zim_filename": f"source_{zim_idx}.zim",
                    },
                    "distance": 0.1 + (i * 0.01)
                })
        
        mock_collection = Mock()
        mock_collection.count.return_value = len(all_chunks)
        
        sorted_chunks = sorted(all_chunks, key=lambda x: x["distance"])
        mock_collection.query.return_value = {
            "ids": [[c["id"] for c in sorted_chunks]],
            "documents": [[c["text"] for c in sorted_chunks]],
            "metadatas": [[c["metadata"] for c in sorted_chunks]],
            "distances": [[c["distance"] for c in sorted_chunks]],
        }
        
        mock_client = Mock()
        mock_client.get_collection.return_value = mock_collection
        
        with patch('chromadb.PersistentClient', return_value=mock_client):
            with patch('langchain_ollama.OllamaEmbeddings') as mock_embed:
                mock_embed.return_value.embed_query.return_value = [0.1] * 768
                chunks = retrieve_chunks_diverse("test", config)
        
        # Should have at most max_sources unique sources
        unique_sources = set(c['metadata']['zim_filename'] for c in chunks)
        assert len(unique_sources) <= config.max_sources, (
            f"Got {len(unique_sources)} unique sources, max_sources={config.max_sources}"
        )


class TestContextFormatting:
    """Tests for context formatting."""

    def test_format_context_shows_diverse_sources(self):
        """Test that context format clearly shows which ZIM each chunk came from."""
        chunks = [
            {
                "text": "CPU stands for Central Processing Unit.",
                "metadata": {
                    "title": "CPU Architecture",
                    "zim_filename": "wikipedia_en_all_maxi_2026-02.zim",
                },
                "distance": 0.1,
            },
            {
                "text": "Transistors form the basis of modern processors.",
                "metadata": {
                    "title": "Transistor Logic",
                    "zim_filename": "electronics.stackexchange.com_en_all_2026-02.zim",
                },
                "distance": 0.15,
            },
            {
                "text": "Quantum mechanics explains semiconductor behavior.",
                "metadata": {
                    "title": "Semiconductor Physics",
                    "zim_filename": "physics.stackexchange.com_en_all_2026-02.zim",
                },
                "distance": 0.2,
            },
        ]
        
        context = format_context(chunks)
        
        # Each source should be clearly labeled with its ZIM file
        assert "wikipedia_en_all_maxi_2026-02.zim" in context
        assert "electronics.stackexchange.com_en_all_2026-02.zim" in context
        assert "physics.stackexchange.com_en_all_2026-02.zim" in context
        
        # Should have source numbers
        assert "Source 1:" in context
        assert "Source 2:" in context
        assert "Source 3:" in context


class TestEndToEndQuery:
    """End-to-end tests for the query pipeline."""

    def test_query_cpu_returns_relevant_diverse_sources(self):
        """E2E test: Query about CPU should return relevant, diverse sources."""
        config = Config(top_k=30, max_sources=10)
        
        # Mock the collection with realistic data
        mock_collection = Mock()
        mock_collection.count.return_value = 10000
        
        relevant_chunks = []
        
        # Wikipedia - most relevant for "How does a CPU work?" (6 chunks)
        for i in range(6):
            relevant_chunks.append({
                "id": f"w{i}",
                "text": f"Wikipedia CPU content {i}",
                "metadata": {"title": f"CPU Article {i}", "zim_filename": "wikipedia_en_all_maxi_2026-02.zim"},
                "distance": 0.05 + (i * 0.01)
            })
        
        # Electronics.SE - implementation details (6 chunks)
        for i in range(6):
            relevant_chunks.append({
                "id": f"e{i}",
                "text": f"Electronics CPU content {i}",
                "metadata": {"title": f"Digital Logic {i}", "zim_filename": "electronics.stackexchange.com_en_all_2026-02.zim"},
                "distance": 0.10 + (i * 0.01)
            })
        
        # Physics.SE - semiconductor physics (6 chunks)
        for i in range(6):
            relevant_chunks.append({
                "id": f"p{i}",
                "text": f"Physics semiconductor content {i}",
                "metadata": {"title": f"Semiconductor {i}", "zim_filename": "physics.stackexchange.com_en_all_2026-02.zim"},
                "distance": 0.15 + (i * 0.01)
            })
        
        # Engineering.SE - manufacturing (6 chunks)
        for i in range(6):
            relevant_chunks.append({
                "id": f"en{i}",
                "text": f"Engineering fabrication content {i}",
                "metadata": {"title": f"Fabrication {i}", "zim_filename": "engineering.stackexchange.com_en_all_2026-02.zim"},
                "distance": 0.20 + (i * 0.01)
            })
        
        # LibreTexts - educational (6 chunks)
        for i in range(6):
            relevant_chunks.append({
                "id": f"l{i}",
                "text": f"LibreTexts architecture content {i}",
                "metadata": {"title": f"Architecture {i}", "zim_filename": "libretexts.org_en_math_2026-01.zim"},
                "distance": 0.25 + (i * 0.01)
            })
        
        sorted_chunks = sorted(relevant_chunks, key=lambda x: x["distance"])
        mock_collection.query.return_value = {
            "ids": [[c["id"] for c in sorted_chunks]],
            "documents": [[c["text"] for c in sorted_chunks]],
            "metadatas": [[c["metadata"] for c in sorted_chunks]],
            "distances": [[c["distance"] for c in sorted_chunks]],
        }
        
        mock_client = Mock()
        mock_client.get_collection.return_value = mock_collection
        
        with patch('chromadb.PersistentClient', return_value=mock_client):
            with patch('langchain_ollama.OllamaEmbeddings') as mock_embed:
                mock_embed.return_value.embed_query.return_value = [0.1] * 768
                chunks = retrieve_chunks_diverse("How does a CPU work?", config)
        
        # Should return diverse, relevant sources
        unique_zims = set(c['metadata']['zim_filename'] for c in chunks)
        
        # Must have Wikipedia for general CPU info
        has_wikipedia = any('wikipedia' in zim.lower() for zim in unique_zims)
        assert has_wikipedia, "CPU query should include Wikipedia as a source"
        
        # Should have at least 3 different sources
        assert len(unique_zims) >= 3, f"Expected 3+ diverse sources, got: {unique_zims}"
        
        # Should NOT be dominated by any single source (max_per_source = ceil(30/5) = 6)
        # So max any source can have is 6/30 = 20%
        for zim in unique_zims:
            count = sum(1 for c in chunks if c['metadata']['zim_filename'] == zim)
            pct = count / len(chunks)
            assert pct <= 0.35, f"Source '{zim}' dominates results: {pct:.1%}"

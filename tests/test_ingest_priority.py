"""Tests for ingestion prioritization of high-value ZIM sources."""

import pytest
from unittest.mock import Mock, patch, MagicMock, call
from pathlib import Path

from zim_rag.ingest import ingest_zim_priority, _zim_priority_key
from zim_rag.config import Config


class TestIngestPriority:
    """Tests that Wikipedia 'all maxi' ZIMs are ingested first."""

    def test_wikipedia_all_maxi_sorted_first(self):
        """Test that Wikipedia all maxi files are prioritized over other sources."""
        zim_files = [
            Path("/zim/electronics.stackexchange.com_en_all_2026-02.zim"),
            Path("/zim/wikipedia_en_all_maxi_2026-02.zim"),  # Should be first
            Path("/zim/physics.stackexchange.com_en_all_2026-02.zim"),
            Path("/zim/wikipedia_en_chemistry_maxi_2026-01.zim"),  # Topic-specific
            Path("/zim/libretexts.org_en_math_2026-01.zim"),
        ]
        
        # Sort using the priority function
        sorted_files = sorted(zim_files, key=_zim_priority_key)
        
        # Wikipedia all maxi should be first
        assert "wikipedia_en_all_maxi" in sorted_files[0].name, \
            f"Expected wikipedia all maxi first, got: {sorted_files[0].name}"
        
        # Check priority order
        names = [f.name for f in sorted_files]
        wiki_all_idx = names.index("wikipedia_en_all_maxi_2026-02.zim")
        electronics_idx = names.index("electronics.stackexchange.com_en_all_2026-02.zim")
        
        assert wiki_all_idx < electronics_idx, \
            "Wikipedia all maxi should be ingested before electronics.SE"

    def test_priority_key_ranking(self):
        """Test the priority key function ranks ZIMs correctly."""
        test_cases = [
            # (filename, expected_rank) - lower rank = higher priority
            ("wikipedia_en_all_maxi_2026-02.zim", 0),  # Highest priority
            ("wikipedia_en_simple_all_maxi_2026-02.zim", 0),  # Also all maxi
            ("wikipedia_en_medicine_maxi_2026-01.zim", 1),  # Topic-specific wiki
            ("wikipedia_en_physics_maxi_2026-01.zim", 1),
            ("electronics.stackexchange.com_en_all_2026-02.zim", 2),  # Other sources
            ("physics.stackexchange.com_en_all_2026-02.zim", 2),
            ("libretexts.org_en_math_2026-01.zim", 2),
            ("gardening.stackexchange.com_en_all_2026-02.zim", 2),
        ]
        
        for filename, expected_rank in test_cases:
            path = Path(f"/zim/{filename}")
            rank = _zim_priority_key(path)
            assert rank[0] == expected_rank, \
                f"{filename}: expected rank {expected_rank}, got {rank[0]}"

    def test_ingest_priority_processes_wiki_first(self):
        """Test that ingest_zim_priority processes Wikipedia files before others."""
        config = Config()
        
        zim_files = [
            Path("/zim/electronics.stackexchange.com_en_all_2026-02.zim"),
            Path("/zim/wikipedia_en_all_maxi_2026-02.zim"),
            Path("/zim/wikipedia_en_physics_maxi_2026-01.zim"),
        ]
        
        ingested_order = []
        
        def mock_ingest(zim_path, config):
            ingested_order.append(Path(zim_path).name)
        
        with patch('zim_rag.ingest.ingest_zim', side_effect=mock_ingest):
            ingest_zim_priority(zim_files, config)
        
        # Wikipedia all maxi should be first
        assert ingested_order[0] == "wikipedia_en_all_maxi_2026-02.zim", \
            f"Expected wiki all maxi first, got: {ingested_order}"
        
        # Then topic-specific wiki
        assert ingested_order[1] == "wikipedia_en_physics_maxi_2026-01.zim", \
            f"Expected topic wiki second, got: {ingested_order}"

    def test_all_maxi_pattern_matching(self):
        """Test that various 'all maxi' patterns are correctly identified."""
        all_maxi_files = [
            "wikipedia_en_all_maxi_2026-02.zim",
            "wikipedia_en_simple_all_maxi_2026-02.zim",
            "wikipedia_de_all_maxi_2026-01.zim",
            "wikipedia_fr_all_maxi_2025-12.zim",
        ]
        
        for filename in all_maxi_files:
            path = Path(f"/zim/{filename}")
            rank = _zim_priority_key(path)
            assert rank[0] == 0, \
                f"{filename} should be priority 0 (all maxi), got {rank[0]}"

    def test_non_wikipedia_sources_lower_priority(self):
        """Test that non-Wikipedia sources get lower priority."""
        non_wiki = [
            "electronics.stackexchange.com_en_all_2026-02.zim",
            "physics.stackexchange.com_en_all_2026-02.zim",
            "engineering.stackexchange.com_en_all_2026-02.zim",
            "libretexts.org_en_math_2026-01.zim",
            "phet_en_all_2026-02.zim",
        ]
        
        for filename in non_wiki:
            path = Path(f"/zim/{filename}")
            rank = _zim_priority_key(path)
            assert rank[0] == 2, \
                f"{filename} should be priority 2 (non-wiki), got {rank[0]}"

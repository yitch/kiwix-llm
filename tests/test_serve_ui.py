"""Behavioral tests for the zim-rag Gradio web UI components."""

import pytest
from pathlib import Path

from zim_rag.config import Config
from zim_rag.serve import (
    DARK_MODE_JS,
    build_ui,
    _list_zim_files,
    _run_ingestion_stream,
    _format_source_citations,
)


@pytest.fixture
def test_config(tmp_path):
    return Config(zim_dir=str(tmp_path))


@pytest.fixture
def app(test_config):
    return build_ui(test_config)


def _find_components(app, component_type):
    """Find all components of a given type name in the app."""
    return [b for b in app.blocks.values() if type(b).__name__ == component_type]


def _find_component_by_value(app, component_type, value_substring):
    """Find a component by type and value containing substring."""
    for b in app.blocks.values():
        if type(b).__name__ == component_type and hasattr(b, "value"):
            if b.value and value_substring in str(b.value):
                return b
    return None


# ── Layout ────────────────────────────────────────────────────────────────────


class TestLayout:
    """Outer Blocks must NOT use fill_height (causes toolbar to go off-screen)."""

    def test_outer_blocks_no_fill_height(self, app):
        import gradio as gr
        assert isinstance(app, gr.Blocks)
        assert app.fill_height is not True

    def test_chat_interface_exists(self, app):
        # ChatInterface is expanded into sub-components; check for Chatbot
        chatbots = _find_components(app, "Chatbot")
        assert len(chatbots) >= 1, "Should contain a Chatbot (from ChatInterface)"


# ── Dark Mode Toggle ─────────────────────────────────────────────────────────


class TestDarkModeToggle:
    """Dark toggle must be a gr.Button with js click handler (NOT gr.HTML)."""

    def test_dark_button_exists(self, app):
        btn = _find_component_by_value(app, "Button", "Dark Mode")
        assert btn is not None, "Should have a Button with 'Dark Mode' in value"

    def test_dark_button_has_js_click(self, app):
        btn = _find_component_by_value(app, "Button", "Dark Mode")
        assert btn is not None
        deps = app.config["dependencies"]
        btn_js_deps = [
            d
            for d in deps
            if d.get("js")
            and any(
                target[0] == btn._id and target[1] == "click"
                for target in d["targets"]
            )
        ]
        assert len(btn_js_deps) >= 1, "Dark button click must have js= parameter"
        assert "zimragToggleTheme" in btn_js_deps[0]["js"]

    def test_no_html_component_for_toggle(self, app):
        """gr.HTML strips onclick — must NOT be used for the toggle."""
        for b in app.blocks.values():
            if type(b).__name__ == "HTML" and hasattr(b, "value") and b.value:
                assert "zimragToggleTheme" not in str(b.value), (
                    "Dark toggle must not be in gr.HTML (onclick is stripped)"
                )

    def test_js_defines_toggle_function(self):
        assert "window.zimragToggleTheme" in DARK_MODE_JS

    def test_js_uses_localstorage(self):
        assert "localStorage.setItem" in DARK_MODE_JS
        assert "localStorage.getItem" in DARK_MODE_JS

    def test_js_respects_system_preference(self):
        assert "prefers-color-scheme: dark" in DARK_MODE_JS


# ── Folder Selection (web-based) ─────────────────────────────────────────────


class TestFolderSelection:
    """Folder selection must be web-based (textbox + scan), not osascript."""

    def test_folder_textbox_exists(self, app):
        textboxes = _find_components(app, "Textbox")
        folder_tb = [
            t
            for t in textboxes
            if hasattr(t, "label")
            and t.label
            and ("folder" in t.label.lower() or "path" in t.label.lower())
        ]
        assert len(folder_tb) >= 1, "Should have a Textbox for folder path"

    def test_scan_button_exists(self, app):
        btn = _find_component_by_value(app, "Button", "Scan")
        assert btn is not None, "Should have a Scan button"

    def test_dropdown_exists(self, app):
        dropdowns = _find_components(app, "Dropdown")
        assert len(dropdowns) >= 1, "Should have a Dropdown for ZIM files"

    def test_list_zim_files_empty_dir(self, tmp_path):
        result = _list_zim_files(str(tmp_path))
        assert "No `.zim` files found" in result

    def test_list_zim_files_with_zims(self, tmp_path):
        (tmp_path / "wiki.zim").touch()
        (tmp_path / "medical.zim").touch()
        result = _list_zim_files(str(tmp_path))
        assert "wiki.zim" in result
        assert "medical.zim" in result
        assert "2 ZIM file(s)" in result

    def test_list_zim_files_nonexistent_dir(self):
        result = _list_zim_files("/nonexistent/path/xyz123")
        assert "not found" in result.lower() or "\u26a0" in result


# ── Ingest Button ────────────────────────────────────────────────────────────


class TestIngestButton:
    """Ingest button should exist and be wired."""

    def test_ingest_button_exists(self, app):
        btn = _find_component_by_value(app, "Button", "Ingest")
        assert btn is not None, "Should have a button with 'Ingest'"

    def test_ingest_button_has_click_handler(self, app):
        btn = _find_component_by_value(app, "Button", "Ingest")
        assert btn is not None
        deps = app.config["dependencies"]
        btn_deps = [
            d
            for d in deps
            if any(
                target[0] == btn._id and target[1] == "click"
                for target in d["targets"]
            )
        ]
        assert len(btn_deps) >= 1, "Ingest button should have a click handler"

    def test_ingestion_stream_invalid_dir(self):
        config = Config(zim_dir="/nonexistent")
        results = list(_run_ingestion_stream("/nonexistent", config))
        assert len(results) >= 1
        assert results[0][2] is True  # has_error

    def test_ingestion_stream_no_zim_files(self, tmp_path):
        config = Config(zim_dir=str(tmp_path))
        results = list(_run_ingestion_stream(str(tmp_path), config))
        assert len(results) >= 1
        assert "No .zim files" in results[0][0]


# ── Accordion ────────────────────────────────────────────────────────────────


class TestAccordion:
    """ZIM section should be in a collapsible Accordion, closed by default."""

    def test_accordion_exists(self, app):
        accordions = _find_components(app, "Accordion")
        assert len(accordions) >= 1, "Should have an Accordion"

    def test_accordion_closed_by_default(self, app):
        accordions = _find_components(app, "Accordion")
        assert any(a.open is False for a in accordions), (
            "At least one Accordion should be closed by default"
        )


# ── Source Citations ─────────────────────────────────────────────────────────


class TestSourceCitations:
    """Source citations should group by ZIM file, not show raw article paths."""

    def test_groups_by_zim_file(self):
        """Sources should be grouped by ZIM filename, not listed per-chunk."""
        chunks = [
            {"metadata": {"title": "a/100723", "zim_filename": "electronics.stackexchange.com_en_all_2026-02.zim"}},
            {"metadata": {"title": "a/100724", "zim_filename": "electronics.stackexchange.com_en_all_2026-02.zim"}},
            {"metadata": {"title": "Photosynthesis", "zim_filename": "wikipedia_en_all_maxi_2026-02.zim"}},
            {"metadata": {"title": "a/50001", "zim_filename": "physics.stackexchange.com_en_all_2026-02.zim"}},
        ]
        result = _format_source_citations(chunks, max_sources=20)
        # Should NOT show raw paths like "a/100723"
        assert "a/100723" not in result
        assert "a/100724" not in result
        # Should show friendly ZIM source names
        assert "electronics" in result.lower()
        assert "stackexchange" in result.lower()
        assert "wikipedia" in result.lower()

    def test_shows_real_titles_when_available(self):
        """When articles have real titles, those should be shown."""
        chunks = [
            {"metadata": {"title": "Photosynthesis", "zim_filename": "wikipedia_en_all_maxi_2026-02.zim"}},
            {"metadata": {"title": "Cellular Respiration", "zim_filename": "wikipedia_en_all_maxi_2026-02.zim"}},
        ]
        result = _format_source_citations(chunks, max_sources=20)
        assert "Photosynthesis" in result
        assert "Cellular Respiration" in result

    def test_deduplicates_zim_sources(self):
        """Multiple chunks from same ZIM should not repeat the ZIM source."""
        chunks = [
            {"metadata": {"title": "a/1", "zim_filename": "electronics.stackexchange.com_en_all_2026-02.zim"}},
            {"metadata": {"title": "a/2", "zim_filename": "electronics.stackexchange.com_en_all_2026-02.zim"}},
            {"metadata": {"title": "a/3", "zim_filename": "electronics.stackexchange.com_en_all_2026-02.zim"}},
        ]
        result = _format_source_citations(chunks, max_sources=20)
        # The ZIM filename should appear at most once as a source heading
        assert result.count("electronics.stackexchange") <= 2  # heading + maybe a title

    def test_respects_max_sources(self):
        """Should limit to max_sources unique ZIM files."""
        chunks = [
            {"metadata": {"title": f"Article {i}", "zim_filename": f"source{i}.zim"}}
            for i in range(30)
        ]
        result = _format_source_citations(chunks, max_sources=5)
        # Should only mention 5 sources
        zim_count = sum(1 for i in range(30) if f"source{i}.zim" in result)
        assert zim_count <= 5

    def test_handles_missing_metadata(self):
        """Should handle chunks with missing title or zim_filename gracefully."""
        chunks = [
            {"metadata": {}},
            {"metadata": {"title": "Good Title"}},
            {"metadata": {"zim_filename": "some.zim"}},
        ]
        result = _format_source_citations(chunks, max_sources=20)
        assert isinstance(result, str)  # Should not crash

    def test_empty_chunks_returns_empty_string(self):
        """No chunks means no sources section."""
        result = _format_source_citations([], max_sources=20)
        assert result == ""

    def test_path_like_titles_are_not_shown_individually(self):
        """Titles that look like paths (a/12345) should not be shown as article titles."""
        chunks = [
            {"metadata": {"title": "a/12345", "zim_filename": "wiki.zim"}},
            {"metadata": {"title": "A/Some Article", "zim_filename": "wiki.zim"}},
        ]
        result = _format_source_citations(chunks, max_sources=20)
        # "a/12345" is a path-like title, should not appear as-is
        assert "a/12345" not in result

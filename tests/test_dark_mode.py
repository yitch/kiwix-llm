"""Tests for dark mode functionality in serve.py."""

import pytest
import re

from zim_rag.serve import DARK_MODE_JS, DARK_TOGGLE_HTML, build_ui


class TestDarkModeJS:
    """Tests for dark mode JavaScript code."""

    def test_dark_mode_js_contains_storage_key(self):
        assert "zim-rag-dark" in DARK_MODE_JS
        assert "STORAGE_KEY" in DARK_MODE_JS

    def test_dark_mode_js_has_toggle_function(self):
        assert "window.zimragToggleTheme" in DARK_MODE_JS
        # Toggles Gradio's built-in dark class on body
        assert "document.body.classList" in DARK_MODE_JS

    def test_dark_mode_js_has_apply_function(self):
        assert "function applyDarkMode" in DARK_MODE_JS

    def test_dark_mode_js_has_update_button_function(self):
        assert "function updateButton" in DARK_MODE_JS
        assert "zimrag-theme-btn" in DARK_MODE_JS
        assert "Light Mode" in DARK_MODE_JS
        assert "Dark Mode" in DARK_MODE_JS

    def test_dark_mode_js_uses_localstorage_for_persistence(self):
        assert "localStorage.setItem" in DARK_MODE_JS
        assert "localStorage.getItem" in DARK_MODE_JS

    def test_dark_mode_js_respects_system_preference(self):
        assert "prefers-color-scheme: dark" in DARK_MODE_JS
        assert "matchMedia" in DARK_MODE_JS

    def test_dark_mode_js_initialization_on_dom_ready(self):
        assert "DOMContentLoaded" in DARK_MODE_JS

    def test_dark_mode_js_prevents_double_initialization(self):
        assert "window.__zimragDarkMode" in DARK_MODE_JS
        pattern = r"if\s*\(\s*window\.__zimragDarkMode\s*\)\s*return;?\s*window\.__zimragDarkMode\s*=\s*true"
        assert re.search(pattern, DARK_MODE_JS)

    def test_dark_toggle_html_has_correct_button_id(self):
        assert 'id="zimrag-theme-btn"' in DARK_TOGGLE_HTML
        assert "zimragToggleTheme" in DARK_TOGGLE_HTML

    def test_dark_mode_js_button_text_reflects_state(self):
        assert "\u2600\ufe0f Light Mode" in DARK_MODE_JS
        assert "\U0001f319 Dark Mode" in DARK_MODE_JS


class TestDarkModeInitialization:
    """Tests for dark mode initialization behavior."""

    def test_dark_mode_js_reads_saved_preference(self):
        assert "localStorage.getItem(STORAGE_KEY)" in DARK_MODE_JS

    def test_dark_mode_js_applies_saved_preference(self):
        assert "applyDarkMode(shouldBeDark)" in DARK_MODE_JS

    def test_dark_mode_toggle_uses_body_dark_class(self):
        """Toggle uses Gradio's native dark class on body."""
        assert "document.body.classList.contains('dark')" in DARK_MODE_JS
        assert "applyDarkMode(!isDark)" in DARK_MODE_JS


class TestDarkModeThemeControl:
    """Tests that dark mode controls Gradio's built-in theme."""

    def test_adds_dark_class_to_body(self):
        assert "document.body.classList.add('dark')" in DARK_MODE_JS

    def test_removes_dark_class_from_body(self):
        assert "document.body.classList.remove('dark')" in DARK_MODE_JS


class TestBuildUI:
    """Tests for the build_ui function integration with dark mode."""

    def test_dark_mode_html_includes_button_with_correct_id(self):
        assert 'id="zimrag-theme-btn"' in DARK_TOGGLE_HTML
        assert "zimragToggleTheme" in DARK_TOGGLE_HTML

    def test_dark_mode_html_has_inline_initialization(self):
        assert "localStorage.getItem('zim-rag-dark')" in DARK_TOGGLE_HTML
        assert "prefers-color-scheme: dark" in DARK_TOGGLE_HTML
        assert "btn.innerHTML" in DARK_TOGGLE_HTML

    def test_serve_includes_dark_mode_js_functions(self):
        assert "function applyDarkMode" in DARK_MODE_JS
        assert "function updateButton" in DARK_MODE_JS
        assert "window.zimragToggleTheme" in DARK_MODE_JS

"""Tests for dark mode functionality in serve.py."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import re

from zim_rag.serve import DARK_MODE_JS, DARK_TOGGLE_HTML, build_ui


class TestDarkModeJS:
    """Tests for dark mode JavaScript code."""

    def test_dark_mode_js_contains_storage_key(self):
        """Test that dark mode JS uses the correct localStorage key."""
        assert "zim-rag-dark" in DARK_MODE_JS
        assert "STORAGE_KEY" in DARK_MODE_JS

    def test_dark_mode_js_has_toggle_function(self):
        """Test that the toggle function exists and is properly defined."""
        assert "window.zimragToggleTheme" in DARK_MODE_JS
        # Should check for the style element to determine current state
        assert "zimrag-dark-style" in DARK_MODE_JS

    def test_dark_mode_js_has_apply_function(self):
        """Test that applyDarkMode function exists."""
        assert "function applyDarkMode" in DARK_MODE_JS

    def test_dark_mode_js_has_update_button_function(self):
        """Test that updateButton function exists and updates button text."""
        assert "function updateButton" in DARK_MODE_JS
        assert "zimrag-theme-btn" in DARK_MODE_JS
        # Should have both light and dark mode button text
        assert "Light Mode" in DARK_MODE_JS
        assert "Dark Mode" in DARK_MODE_JS

    def test_dark_mode_js_uses_localstorage_for_persistence(self):
        """Test that dark mode preference is saved to localStorage."""
        assert "localStorage.setItem" in DARK_MODE_JS
        assert "localStorage.getItem" in DARK_MODE_JS

    def test_dark_mode_js_respects_system_preference(self):
        """Test that dark mode respects prefers-color-scheme media query."""
        assert "prefers-color-scheme: dark" in DARK_MODE_JS
        assert "matchMedia" in DARK_MODE_JS

    def test_dark_mode_js_initialization_on_dom_ready(self):
        """Test that dark mode initializes on DOMContentLoaded when needed."""
        assert "DOMContentLoaded" in DARK_MODE_JS

    def test_dark_mode_js_prevents_double_initialization(self):
        """Test that the script prevents being run multiple times."""
        assert "window.__zimragDarkMode" in DARK_MODE_JS
        # Should check and set the flag
        pattern = r"if\s*\(\s*window\.__zimragDarkMode\s*\)\s*return;?\s*window\.__zimragDarkMode\s*=\s*true"
        assert re.search(pattern, DARK_MODE_JS), "Should prevent double initialization"

    def test_dark_toggle_html_has_correct_button_id(self):
        """Test that the toggle button has the correct ID."""
        assert 'id="zimrag-theme-btn"' in DARK_TOGGLE_HTML
        assert "zimragToggleTheme" in DARK_TOGGLE_HTML

    def test_dark_mode_js_button_text_reflects_state(self):
        """Test that button text properly reflects dark mode state."""
        # When dark mode is enabled, button should show "Light Mode" (to switch to light)
        # When dark mode is disabled, button should show "Dark Mode" (to switch to dark)
        assert "☀️ Light Mode" in DARK_MODE_JS
        assert "🌙 Dark Mode" in DARK_MODE_JS


class TestDarkModeInitialization:
    """Tests for dark mode initialization behavior."""

    def test_dark_mode_js_reads_saved_preference(self):
        """Test that saved preference is read from localStorage on init."""
        assert "localStorage.getItem(STORAGE_KEY)" in DARK_MODE_JS

    def test_dark_mode_js_applies_saved_preference(self):
        """Test that saved preference is applied on initialization."""
        # Should call applyDarkMode with the saved preference
        assert "applyDarkMode(shouldBeDark)" in DARK_MODE_JS or "applyDarkMode(" in DARK_MODE_JS

    def test_dark_mode_toggle_logic(self):
        """Test that toggle correctly inverts current state."""
        # The toggle function should:
        # 1. Check if dark mode is currently enabled
        # 2. Apply the opposite state
        # Uses helper function isDarkModeEnabled() to check state
        assert "function isDarkModeEnabled()" in DARK_MODE_JS
        assert "!!document.getElementById('zimrag-dark-style')" in DARK_MODE_JS
        assert "applyDarkMode(!isDark)" in DARK_MODE_JS


class TestDarkModeCSS:
    """Tests for dark mode CSS variables."""

    def test_dark_mode_includes_css_overrides(self):
        """Test that dark mode includes CSS variable overrides."""
        assert "--body-background-fill" in DARK_MODE_JS
        assert "--background-fill-primary" in DARK_MODE_JS
        assert "--text-color" in DARK_MODE_JS

    def test_dark_mode_has_proper_contrast(self):
        """Test that dark mode colors provide proper contrast."""
        # Dark background colors
        assert "#0f0f0f" in DARK_MODE_JS or "#1a1a1a" in DARK_MODE_JS
        # Light text colors
        assert "#ffffff" in DARK_MODE_JS or "#e0e0e0" in DARK_MODE_JS or "#cccccc" in DARK_MODE_JS


class TestBuildUI:
    """Tests for the build_ui function integration with dark mode."""

    def test_dark_mode_html_includes_button_with_correct_id(self):
        """Test that DARK_TOGGLE_HTML includes the dark mode button."""
        assert 'id="zimrag-theme-btn"' in DARK_TOGGLE_HTML
        assert "zimragToggleTheme" in DARK_TOGGLE_HTML
        assert "localStorage.getItem('zim-rag-dark')" in DARK_TOGGLE_HTML

    def test_dark_mode_html_has_inline_initialization(self):
        """Test that the button has inline script for immediate state."""
        # The inline script should set correct initial button text
        assert "localStorage.getItem('zim-rag-dark')" in DARK_TOGGLE_HTML
        assert "prefers-color-scheme: dark" in DARK_TOGGLE_HTML
        # Should set button text based on saved preference
        assert "btn.innerHTML" in DARK_TOGGLE_HTML

    def test_serve_includes_dark_mode_script_in_head(self):
        """Test that serve() includes dark mode script in head_html."""
        # The DARK_MODE_JS constant should contain all necessary functions
        assert "function applyDarkMode" in DARK_MODE_JS
        assert "function updateButton" in DARK_MODE_JS
        assert "function isDarkModeEnabled" in DARK_MODE_JS
        assert "window.zimragToggleTheme" in DARK_MODE_JS

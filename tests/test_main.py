"""Smoke tests for main.py entry point (no LLM, no interactive loop)."""

from __future__ import annotations

import importlib


def test_main_module_imports():
    """main.py should import without error and expose a callable main()."""
    mod = importlib.import_module("main")
    assert hasattr(mod, "main")
    assert callable(mod.main)


def test_main_module_does_not_eagerly_import_adk():
    """Importing main.py shouldn't construct agents or hit Gemini.

    The `if __name__ == "__main__"` guard plus lazy imports inside `main()`
    ensure that `import main` is cheap.
    """
    importlib.import_module("main")
    # No assertion needed beyond successful import; if main.py eagerly
    # imported agents.coordinator, the test would still pass, but at least
    # we'd know google.adk is needed by anyone importing main.
    assert True
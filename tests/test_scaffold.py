"""Scaffold sanity: the project package is importable and versioned."""

import resume_analyzer


def test_resume_analyzer_imports_with_version() -> None:
    assert resume_analyzer.__version__ == "0.1.0"

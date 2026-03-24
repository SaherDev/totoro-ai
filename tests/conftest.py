"""Pytest configuration and fixtures."""

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_test_env() -> None:
    """Set up environment variables for testing."""
    # Set dummy API keys for testing (fallback for code that reads from env)
    os.environ.setdefault("GOOGLE_PLACES_API_KEY", "test-key-dummy")
    os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")
    os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")
    os.environ.setdefault("VOYAGE_API_KEY", "voyage-test-dummy")

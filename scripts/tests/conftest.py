"""Shared test setup for scripts/tests."""

import os

import pytest


@pytest.fixture(autouse=True)
def no_outer_git(monkeypatch):
    """Drop the GIT_* variables a git hook exports (GIT_DIR, GIT_INDEX_FILE, ...).

    The pre-commit hook runs these tests. With those variables inherited, a test
    that runs git in a temp repo acts on the repo being committed to instead: it
    once set core.bare=true, wrote user.name/user.email and committed into it.
    """
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)

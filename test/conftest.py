"""Keep the suite hermetic with respect to SNIPPET_CAST_* environment.

Every option has a `SNIPPET_CAST_<NAME>` env var, and a project-wide
activation env (pixi's `[tool.pixi.activation.env]`, a shell profile, a CI
secret) can set any of them for the whole process. That silently rewrites the
defaults the tests assert against — a run with all of them materialised at
their documented values turned seven tests red without a single source change.

Tests that exercise an env var set it themselves via `monkeypatch.setenv`, so
clearing the namespace up front costs nothing and makes a local run agree with
a clean one.
"""
import os

import pytest


@pytest.fixture(autouse=True)
def _clear_snippet_cast_env(monkeypatch):
    for name in [k for k in os.environ if k.startswith("SNIPPET_CAST_")]:
        monkeypatch.delenv(name, raising=False)

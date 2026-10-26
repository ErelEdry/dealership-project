"""Shared fixtures."""

import importlib
import sys
import types

import pytest


@pytest.fixture
def search_route(monkeypatch):
    """app.api.routes.search with a stub embedder (avoids the 130 MB model load).

    Tests set `embed_query` / `get_qdrant` / `_redis` on the returned module.
    """
    embedder = types.ModuleType("app.etl.embedder")
    embedder.embed_query = embedder.get_qdrant = None
    monkeypatch.setitem(sys.modules, "app.etl.embedder", embedder)
    monkeypatch.delitem(sys.modules, "app.api.routes.search", raising=False)
    mod = importlib.import_module("app.api.routes.search")
    monkeypatch.delitem(sys.modules, "app.api.routes.search")   # don't leak the stubbed copy
    return mod

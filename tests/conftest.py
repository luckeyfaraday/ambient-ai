from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from ambient_ai.events import EventStore
from ambient_ai.paths import AmbientPaths


@pytest.fixture
def tmp_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def paths(tmp_root: Path) -> AmbientPaths:
    p = AmbientPaths.from_env(tmp_root)
    p.ensure()
    return p


@pytest.fixture
def store(paths: AmbientPaths) -> EventStore:
    s = EventStore(paths.db_path)
    s.init()
    return s

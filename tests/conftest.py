"""Shared pytest fixtures."""
from __future__ import annotations
import sqlite3
from pathlib import Path
import pytest

def create_hermes_db(path: Path, *, version: int = 26, include_usage: bool = True) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path); conn.row_factory = sqlite3.Row
    conn.executescript(f"""
    CREATE TABLE schema_version(version INTEGER NOT NULL); INSERT INTO schema_version(version) VALUES ({version});
    CREATE TABLE sessions(id TEXT PRIMARY KEY, source TEXT, profile_name TEXT, parent_session_id TEXT, started_at REAL, ended_at REAL, title TEXT, model TEXT, billing_provider TEXT NOT NULL DEFAULT '', billing_base_url TEXT NOT NULL DEFAULT '', billing_mode TEXT NOT NULL DEFAULT '', api_call_count INTEGER NOT NULL DEFAULT 0, input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0, cache_read_tokens INTEGER NOT NULL DEFAULT 0, cache_write_tokens INTEGER NOT NULL DEFAULT 0, reasoning_tokens INTEGER NOT NULL DEFAULT 0, estimated_cost_usd REAL NOT NULL DEFAULT 0, actual_cost_usd REAL NOT NULL DEFAULT 0, cost_status TEXT, cost_source TEXT);
    """)
    if include_usage:
        conn.executescript("""
        CREATE TABLE session_model_usage(session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, model TEXT NOT NULL, billing_provider TEXT NOT NULL DEFAULT '', billing_base_url TEXT NOT NULL DEFAULT '', billing_mode TEXT NOT NULL DEFAULT '', task TEXT NOT NULL DEFAULT '', api_call_count INTEGER NOT NULL DEFAULT 0, input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0, cache_read_tokens INTEGER NOT NULL DEFAULT 0, cache_write_tokens INTEGER NOT NULL DEFAULT 0, reasoning_tokens INTEGER NOT NULL DEFAULT 0, estimated_cost_usd REAL NOT NULL DEFAULT 0, actual_cost_usd REAL NOT NULL DEFAULT 0, cost_status TEXT, cost_source TEXT, first_seen REAL, last_seen REAL, PRIMARY KEY(session_id, model, billing_provider, billing_base_url, billing_mode, task));
        """)
    conn.commit(); return conn

@pytest.fixture
def hermes_home(tmp_path: Path) -> Path: return tmp_path / "hermes"
@pytest.fixture
def hermes_db(hermes_home: Path):
    conn = create_hermes_db(hermes_home / "state.db"); yield conn; conn.close()

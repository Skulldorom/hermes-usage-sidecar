from __future__ import annotations
import sqlite3
from pathlib import Path
import pytest
from hermes_usage_sidecar.db import SchemaMismatchError, discover_profile_dbs, fetch_usage_rows, ro_connect, schema_version, validate_schema
from tests.conftest import create_hermes_db

def test_discovers_default_and_profiles(hermes_home: Path):
    (hermes_home / "state.db").parent.mkdir(parents=True, exist_ok=True); (hermes_home / "state.db").touch()
    (hermes_home / "profiles" / "coder").mkdir(parents=True); (hermes_home / "profiles" / "coder" / "state.db").touch()
    assert [d.profile for d in discover_profile_dbs(hermes_home)] == ["default", "coder"]

def test_ro_connect_sets_query_only_and_rejects_write(hermes_home: Path):
    create_hermes_db(hermes_home / "state.db").close(); ro = ro_connect(hermes_home / "state.db")
    try:
        assert ro.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError): ro.execute("CREATE TABLE nope(id INTEGER)")
    finally: ro.close()

def test_schema_validation_and_extraction(hermes_db):
    hermes_db.execute("INSERT INTO sessions(id, source, started_at, ended_at, model, billing_provider, input_tokens, output_tokens) VALUES ('s1','cli',1,2,'anthropic/claude-sonnet-4','anthropic',100,50)")
    hermes_db.execute("INSERT INTO session_model_usage(session_id, model, billing_provider, billing_mode, api_call_count, input_tokens, output_tokens, first_seen, last_seen, cost_status, estimated_cost_usd) VALUES ('s1','anthropic/claude-sonnet-4','anthropic','chat',1,100,50,1,2.123456,'estimated',0.02)")
    hermes_db.commit(); assert schema_version(hermes_db) == 26; assert validate_schema(hermes_db) == 26
    rows = fetch_usage_rows(hermes_db, since=0); assert len(rows) == 1; assert rows[0]["last_seen"] == 2.123456

def test_current_stable_schema_version_is_supported(hermes_home: Path):
    conn = create_hermes_db(hermes_home / "state.db", version=30)
    assert validate_schema(conn) == 30
    conn.close()

def test_unknown_schema_version_is_error(hermes_home: Path):
    conn = create_hermes_db(hermes_home / "state.db", version=99)
    with pytest.raises(SchemaMismatchError): validate_schema(conn)
    conn.close()

def test_missing_usage_columns_is_error(hermes_home: Path):
    conn = create_hermes_db(hermes_home / "state.db", include_usage=False)
    with pytest.raises(SchemaMismatchError): validate_schema(conn)
    conn.close()

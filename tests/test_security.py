from __future__ import annotations
import sqlite3
from fastapi.testclient import TestClient
from hermes_usage_sidecar import db as dbmod
from hermes_usage_sidecar.config import Settings
from hermes_usage_sidecar.server import create_app

def test_response_never_contains_conversation_content(hermes_home, tmp_path):
    hermes_home.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(hermes_home / "state.db")
    conn.executescript("""
    CREATE TABLE schema_version(version INTEGER); INSERT INTO schema_version VALUES (26);
    CREATE TABLE sessions(id TEXT PRIMARY KEY, source TEXT, profile_name TEXT, parent_session_id TEXT, started_at REAL, ended_at REAL, title TEXT, model TEXT, billing_provider TEXT DEFAULT '', billing_base_url TEXT DEFAULT '', billing_mode TEXT DEFAULT '', api_call_count INTEGER DEFAULT 0, input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0, cache_read_tokens INTEGER DEFAULT 0, cache_write_tokens INTEGER DEFAULT 0, reasoning_tokens INTEGER DEFAULT 0, estimated_cost_usd REAL DEFAULT 0, actual_cost_usd REAL DEFAULT 0, cost_status TEXT, cost_source TEXT);
    CREATE TABLE session_model_usage(session_id TEXT, model TEXT, billing_provider TEXT DEFAULT '', billing_base_url TEXT DEFAULT '', billing_mode TEXT DEFAULT '', task TEXT DEFAULT '', api_call_count INTEGER DEFAULT 0, input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0, cache_read_tokens INTEGER DEFAULT 0, cache_write_tokens INTEGER DEFAULT 0, reasoning_tokens INTEGER DEFAULT 0, estimated_cost_usd REAL DEFAULT 0, actual_cost_usd REAL DEFAULT 0, cost_status TEXT, cost_source TEXT, first_seen REAL, last_seen REAL);
    CREATE TABLE messages(id INTEGER, session_id TEXT, role TEXT, content TEXT);
    INSERT INTO sessions(id, started_at, ended_at, model, billing_provider) VALUES ('s1',1,2,'m','p');
    INSERT INTO session_model_usage(session_id, model, billing_provider, api_call_count, input_tokens, first_seen, last_seen) VALUES ('s1','m','p',1,1,1,2);
    INSERT INTO messages VALUES (1,'s1','user','SECRET CONVERSATION');
    """)
    conn.commit(); conn.close()
    body = TestClient(create_app(Settings(hermes_home=hermes_home, state_db=tmp_path / 'state.db'))).get('/usage').json()
    text = str(body).lower(); assert 'secret conversation' not in text
    for forbidden in ('content', 'role', 'message'): assert forbidden not in text

def test_sql_never_queries_messages_or_select_star():
    sql_values = [v for k, v in vars(dbmod).items() if k.endswith('SQL') and isinstance(v, str)]
    assert sql_values
    for sql in sql_values:
        assert 'select *' not in sql.lower(); assert 'messages' not in sql.lower()

def test_wrong_token_not_logged(caplog, hermes_home, tmp_path):
    app = create_app(Settings(hermes_home=hermes_home, state_db=tmp_path / 'state.db', token='correct-token'))
    assert TestClient(app).get('/usage', headers={'Authorization':'Bearer wrong-token'}).status_code == 401
    assert 'wrong-token' not in caplog.text and 'correct-token' not in caplog.text

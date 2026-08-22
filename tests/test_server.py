from __future__ import annotations
from pathlib import Path
from fastapi.testclient import TestClient
from hermes_usage_sidecar.config import Settings
from hermes_usage_sidecar.server import create_app
from tests.conftest import create_hermes_db

def _app(home: Path, state_db: Path, token: str | None = "secret"):
    return create_app(Settings(hermes_home=home, state_db=state_db, token=token))

def test_usage_endpoint_contract_and_auth(hermes_home: Path, tmp_path: Path):
    conn = create_hermes_db(hermes_home / "state.db")
    conn.execute("INSERT INTO sessions(id, source, started_at, ended_at, model, billing_provider) VALUES ('s1','cli',1,2,'anthropic/claude-sonnet-4:free','Anthropic')")
    conn.execute("INSERT INTO session_model_usage(session_id, model, billing_provider, api_call_count, input_tokens, output_tokens, first_seen, last_seen, cost_status, estimated_cost_usd) VALUES ('s1','anthropic/claude-sonnet-4:free','Anthropic',1,100,50,1,2.25,'estimated',0.02)")
    conn.commit(); conn.close()
    client = TestClient(_app(hermes_home, tmp_path / "state.db"))
    assert client.get("/usage").status_code == 401
    body = client.get("/usage", headers={"Authorization":"Bearer secret"}).json()
    obs = body["observations"][0]
    assert body["watermark"] == 2.25
    assert set(obs) == {"event_id","timestamp","provider","model","profile","session_id","input_tokens","output_tokens","cache_read_tokens","cache_write_tokens","reasoning_tokens","requests","cost","cost_type"}
    assert obs["provider"] == "anthropic" and obs["model"] == "claude-sonnet-4" and obs["profile"] == "default"
    assert client.get("/usage", headers={"Authorization":"Bearer secret"}).json()["observations"] == []

def test_profile_filter_and_healthz(hermes_home: Path, tmp_path: Path):
    create_hermes_db(hermes_home / "state.db").close()
    coder = create_hermes_db(hermes_home / "profiles" / "coder" / "state.db")
    coder.execute("INSERT INTO sessions(id, source, started_at, ended_at, model, billing_provider) VALUES ('s1','cli',1,2,'m','p')")
    coder.execute("INSERT INTO session_model_usage(session_id, model, billing_provider, api_call_count, input_tokens, first_seen, last_seen) VALUES ('s1','m','p',1,10,1,2)")
    coder.commit(); coder.close()
    client = TestClient(_app(hermes_home, tmp_path / "sidecar.db", token=None))
    assert client.get("/healthz").json()["schema_versions"] == {"default": 26, "coder": 26}
    assert client.get("/usage?profile=coder").json()["observations"][0]["profile"] == "coder"

def test_schema_error_returns_409(hermes_home: Path, tmp_path: Path):
    create_hermes_db(hermes_home / "state.db", version=99).close()
    response = TestClient(_app(hermes_home, tmp_path / "state.db", token=None)).get("/usage")
    assert response.status_code == 409

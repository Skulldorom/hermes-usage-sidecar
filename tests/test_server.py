from __future__ import annotations
import sqlite3
from pathlib import Path
from fastapi.testclient import TestClient
from hermes_usage_sidecar.config import Settings
from hermes_usage_sidecar.server import create_app
from tests.conftest import create_hermes_db


def _app(home: Path, state_db: Path, token: str | None = "secret"):
    return create_app(Settings(hermes_home=home, state_db=state_db, token=token))


def _insert_usage(conn, *, session_id: str = "s1", profile_model: str = "anthropic/claude-sonnet-4:free", provider: str = "Anthropic", calls: int = 1, input_tokens: int = 100, output_tokens: int = 50, first_seen: float = 1, last_seen: float = 2.25, estimated_cost: float = 0.02):
    conn.execute(
        "INSERT INTO sessions(id, source, started_at, ended_at, model, billing_provider) VALUES (?,?,?,?,?,?)",
        (session_id, "cli", first_seen, last_seen, profile_model, provider),
    )
    conn.execute(
        "INSERT INTO session_model_usage(session_id, model, billing_provider, api_call_count, input_tokens, output_tokens, first_seen, last_seen, cost_status, estimated_cost_usd) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (session_id, profile_model, provider, calls, input_tokens, output_tokens, first_seen, last_seen, "estimated", estimated_cost),
    )


def test_usage_endpoint_contract_and_auth(hermes_home: Path, tmp_path: Path):
    conn = create_hermes_db(hermes_home / "state.db")
    _insert_usage(conn)
    conn.commit(); conn.close()
    client = TestClient(_app(hermes_home, tmp_path / "state.db"))
    assert client.get("/usage").status_code == 401
    body = client.get("/usage", headers={"Authorization":"Bearer secret"}).json()
    obs = body["observations"][0]
    assert body["watermark"] == 2.25
    assert set(obs) == {"event_id","timestamp","provider","model","profile","session_id","input_tokens","output_tokens","cache_read_tokens","cache_write_tokens","reasoning_tokens","requests","cost","cost_type"}
    assert obs["provider"] == "anthropic" and obs["model"] == "claude-sonnet-4" and obs["profile"] == "default"
    repeat = client.get("/usage", headers={"Authorization":"Bearer secret"}).json()
    assert repeat == body


def test_usage_since_is_consumer_owned_and_idempotent(hermes_home: Path, tmp_path: Path):
    conn = create_hermes_db(hermes_home / "state.db")
    _insert_usage(conn)
    conn.commit(); conn.close()

    state_db = tmp_path / "state.db"
    consumer_a = TestClient(_app(hermes_home, state_db, token=None))
    first = consumer_a.get("/usage?since=0").json()
    assert len(first["observations"]) == 1
    assert first["observations"][0]["input_tokens"] == 100
    assert first["watermark"] == 2.25

    assert consumer_a.get(f"/usage?since={first['watermark']}").json() == {"observations": [], "watermark": 2.25}
    assert consumer_a.get("/usage?since=0").json() == first

    consumer_b = TestClient(_app(hermes_home, state_db, token=None))
    assert consumer_b.get("/usage?since=0").json() == first


def test_usage_returns_delta_after_consumer_watermark_and_survives_restart(hermes_home: Path, tmp_path: Path):
    conn = create_hermes_db(hermes_home / "state.db")
    _insert_usage(conn)
    conn.commit(); conn.close()

    state_db = tmp_path / "state.db"
    client = TestClient(_app(hermes_home, state_db, token=None))
    first = client.get("/usage?since=0").json()
    assert first["watermark"] == 2.25

    hermes = sqlite3.connect(hermes_home / "state.db")
    hermes.execute("UPDATE sessions SET ended_at=3.5, api_call_count=3, input_tokens=175, output_tokens=80, estimated_cost_usd=0.04 WHERE id='s1'")
    hermes.execute("UPDATE session_model_usage SET api_call_count=3, input_tokens=175, output_tokens=80, last_seen=3.5, estimated_cost_usd=0.04 WHERE session_id='s1'")
    hermes.commit(); hermes.close()

    restarted_client = TestClient(_app(hermes_home, state_db, token=None))
    second = restarted_client.get(f"/usage?since={first['watermark']}").json()
    assert second["watermark"] == 3.5
    assert len(second["observations"]) == 1
    assert second["observations"][0]["input_tokens"] == 75
    assert second["observations"][0]["output_tokens"] == 30
    assert second["observations"][0]["requests"] == 2

    bootstrap = restarted_client.get("/usage?since=0").json()
    assert [obs["input_tokens"] for obs in bootstrap["observations"]] == [100, 75]


def test_usage_includes_multiple_profiles_with_independent_history(hermes_home: Path, tmp_path: Path):
    default = create_hermes_db(hermes_home / "state.db")
    _insert_usage(default, session_id="default-session", input_tokens=10, output_tokens=5, last_seen=2)
    default.commit(); default.close()
    coder = create_hermes_db(hermes_home / "profiles" / "coder" / "state.db")
    _insert_usage(coder, session_id="coder-session", profile_model="m", provider="p", input_tokens=20, output_tokens=10, last_seen=3)
    coder.commit(); coder.close()

    client = TestClient(_app(hermes_home, tmp_path / "sidecar.db", token=None))
    body = client.get("/usage?since=0").json()
    assert body["watermark"] == 3
    assert {obs["profile"] for obs in body["observations"]} == {"default", "coder"}
    assert client.get("/usage?profile=coder&since=0").json()["observations"][0]["profile"] == "coder"


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

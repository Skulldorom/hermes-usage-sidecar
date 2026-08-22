from __future__ import annotations
from hermes_usage_sidecar.delta import WatermarkStore, compute_deltas
from hermes_usage_sidecar.db import fetch_usage_rows

def test_watermark_store_roundtrip(tmp_path):
    store = WatermarkStore(tmp_path / "sidecar" / "state.db"); store.set("coder", "key", 1.123456, {"input_tokens": 10}); store.close()
    store = WatermarkStore(tmp_path / "sidecar" / "state.db"); assert store.get("coder", "key") == ("1.123456", {"input_tokens": 10}); store.close()

def test_compute_deltas_skips_unchanged(tmp_path):
    store = WatermarkStore(tmp_path / "state.db")
    row = {"session_id":"s1","model":"anthropic/claude","billing_provider":"anthropic","billing_base_url":"","billing_mode":"chat","task":"","api_call_count":1,"input_tokens":100,"output_tokens":20,"cache_read_tokens":0,"cache_write_tokens":0,"reasoning_tokens":0,"estimated_cost_usd":0.01,"actual_cost_usd":0,"cost_status":"estimated","last_seen":10.5}
    assert compute_deltas([row], store, "coder", tmp_path / "hermes" / "state.db")[0].input_tokens == 100
    assert compute_deltas([row], store, "coder", tmp_path / "hermes" / "state.db") == []
    row2 = {**row, "api_call_count":3, "input_tokens":300, "output_tokens":40, "estimated_cost_usd":0.03, "last_seen":11.25}
    second = compute_deltas([row2], store, "coder", tmp_path / "hermes" / "state.db"); assert second[0].input_tokens == 200; assert second[0].requests == 2
    store.close()

def test_legacy_reconciliation_counts_residual_only(hermes_db):
    hermes_db.execute("INSERT INTO sessions(id, source, started_at, ended_at, model, billing_provider, api_call_count, input_tokens, output_tokens, estimated_cost_usd, cost_status) VALUES ('legacy','cli',1,2,'m','p',1,500,0,0.5,'estimated')")
    hermes_db.execute("INSERT INTO sessions(id, source, started_at, ended_at, model, billing_provider, api_call_count, input_tokens, output_tokens, estimated_cost_usd, cost_status) VALUES ('partial','cli',1,3,'m','p',3,500,100,0.5,'estimated')")
    hermes_db.execute("INSERT INTO session_model_usage(session_id, model, billing_provider, api_call_count, input_tokens, output_tokens, estimated_cost_usd, first_seen, last_seen, cost_status) VALUES ('partial','m','p',2,300,100,0.3,1,3,'estimated')")
    hermes_db.commit(); rows = fetch_usage_rows(hermes_db, since=0); by_id = {(r['session_id'], r['legacy_residual']): r for r in rows}
    assert by_id[("legacy", 1)]["input_tokens"] == 500; assert by_id[("partial", 0)]["input_tokens"] == 300; assert by_id[("partial", 1)]["input_tokens"] == 200

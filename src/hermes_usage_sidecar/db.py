"""Read-only Hermes state.db discovery and extraction."""
from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUPPORTED_SCHEMA_VERSIONS = frozenset(range(22, 27))
REQUIRED_SESSION_COLUMNS = {"id","source","profile_name","parent_session_id","started_at","ended_at","title","model","billing_provider","billing_base_url","billing_mode","api_call_count","input_tokens","output_tokens","cache_read_tokens","cache_write_tokens","reasoning_tokens","estimated_cost_usd","actual_cost_usd","cost_status","cost_source"}
REQUIRED_USAGE_COLUMNS = {"session_id","model","billing_provider","billing_base_url","billing_mode","task","api_call_count","input_tokens","output_tokens","cache_read_tokens","cache_write_tokens","reasoning_tokens","estimated_cost_usd","actual_cost_usd","cost_status","cost_source","first_seen","last_seen"}
EXTRACTION_SQL = """
SELECT u.session_id, u.model, u.billing_provider, u.billing_base_url,
       u.billing_mode, COALESCE(u.task, '') AS task,
       COALESCE(u.api_call_count, 0) AS api_call_count,
       COALESCE(u.input_tokens, 0) AS input_tokens,
       COALESCE(u.output_tokens, 0) AS output_tokens,
       COALESCE(u.cache_read_tokens, 0) AS cache_read_tokens,
       COALESCE(u.cache_write_tokens, 0) AS cache_write_tokens,
       COALESCE(u.reasoning_tokens, 0) AS reasoning_tokens,
       COALESCE(u.estimated_cost_usd, 0) AS estimated_cost_usd,
       COALESCE(u.actual_cost_usd, 0) AS actual_cost_usd,
       u.cost_status, u.cost_source, u.first_seen, u.last_seen,
       s.source AS platform, s.profile_name, s.parent_session_id,
       s.started_at, s.ended_at, s.title, 0 AS legacy_residual
FROM session_model_usage u JOIN sessions s ON s.id = u.session_id
WHERE COALESCE(u.last_seen, 0) > ?
ORDER BY COALESCE(u.last_seen, 0), u.session_id, u.model, u.billing_provider, u.billing_base_url, u.billing_mode, COALESCE(u.task, '')
"""
LEGACY_RECONCILIATION_SQL = """
WITH usage_totals AS (
    SELECT session_id,
           COALESCE(SUM(input_tokens), 0) AS input_tokens,
           COALESCE(SUM(output_tokens), 0) AS output_tokens,
           COALESCE(SUM(cache_read_tokens), 0) AS cache_read_tokens,
           COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
           COALESCE(SUM(reasoning_tokens), 0) AS reasoning_tokens,
           COALESCE(SUM(api_call_count), 0) AS api_call_count,
           COALESCE(SUM(estimated_cost_usd), 0) AS estimated_cost_usd,
           COALESCE(SUM(actual_cost_usd), 0) AS actual_cost_usd
    FROM session_model_usage GROUP BY session_id
)
SELECT s.id AS session_id, COALESCE(s.model, 'unknown') AS model,
       COALESCE(s.billing_provider, '') AS billing_provider,
       COALESCE(s.billing_base_url, '') AS billing_base_url,
       COALESCE(s.billing_mode, '') AS billing_mode,
       '__legacy_session_residual__' AS task,
       MAX(0, COALESCE(s.api_call_count, 0) - COALESCE(u.api_call_count, 0)) AS api_call_count,
       MAX(0, COALESCE(s.input_tokens, 0) - COALESCE(u.input_tokens, 0)) AS input_tokens,
       MAX(0, COALESCE(s.output_tokens, 0) - COALESCE(u.output_tokens, 0)) AS output_tokens,
       MAX(0, COALESCE(s.cache_read_tokens, 0) - COALESCE(u.cache_read_tokens, 0)) AS cache_read_tokens,
       MAX(0, COALESCE(s.cache_write_tokens, 0) - COALESCE(u.cache_write_tokens, 0)) AS cache_write_tokens,
       MAX(0, COALESCE(s.reasoning_tokens, 0) - COALESCE(u.reasoning_tokens, 0)) AS reasoning_tokens,
       MAX(0.0, COALESCE(s.estimated_cost_usd, 0) - COALESCE(u.estimated_cost_usd, 0)) AS estimated_cost_usd,
       MAX(0.0, COALESCE(s.actual_cost_usd, 0) - COALESCE(u.actual_cost_usd, 0)) AS actual_cost_usd,
       s.cost_status, s.cost_source, s.started_at AS first_seen,
       COALESCE(s.ended_at, s.started_at) AS last_seen,
       s.source AS platform, s.profile_name, s.parent_session_id,
       s.started_at, s.ended_at, s.title, 1 AS legacy_residual
FROM sessions s LEFT JOIN usage_totals u ON u.session_id = s.id
WHERE COALESCE(s.ended_at, s.started_at, 0) > ?
  AND (MAX(0, COALESCE(s.api_call_count, 0) - COALESCE(u.api_call_count, 0)) > 0
    OR MAX(0, COALESCE(s.input_tokens, 0) - COALESCE(u.input_tokens, 0)) > 0
    OR MAX(0, COALESCE(s.output_tokens, 0) - COALESCE(u.output_tokens, 0)) > 0
    OR MAX(0, COALESCE(s.cache_read_tokens, 0) - COALESCE(u.cache_read_tokens, 0)) > 0
    OR MAX(0, COALESCE(s.cache_write_tokens, 0) - COALESCE(u.cache_write_tokens, 0)) > 0
    OR MAX(0, COALESCE(s.reasoning_tokens, 0) - COALESCE(u.reasoning_tokens, 0)) > 0
    OR MAX(0.0, COALESCE(s.estimated_cost_usd, 0) - COALESCE(u.estimated_cost_usd, 0)) > 0
    OR MAX(0.0, COALESCE(s.actual_cost_usd, 0) - COALESCE(u.actual_cost_usd, 0)) > 0)
ORDER BY COALESCE(s.ended_at, s.started_at, 0), s.id
"""

@dataclass(frozen=True)
class ProfileDB:
    profile: str
    path: Path
class SchemaMismatchError(RuntimeError):
    pass

def discover_profile_dbs(hermes_home: Path) -> list[ProfileDB]:
    home = Path(hermes_home).expanduser()
    out: list[ProfileDB] = []
    if (home / "state.db").exists():
        out.append(ProfileDB("default", home / "state.db"))
    profiles = home / "profiles"
    if profiles.exists():
        out.extend(ProfileDB(p.parent.name, p) for p in sorted(profiles.glob("*/state.db"), key=lambda p: p.parent.name))
    return out

def ro_connect(path: Path) -> sqlite3.Connection:
    uri = f"file:{Path(path).expanduser().resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn

def schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT version FROM schema_version LIMIT 1").fetchone()
    except sqlite3.Error as exc:
        raise SchemaMismatchError("missing schema_version table") from exc
    if row is None:
        raise SchemaMismatchError("schema_version table is empty")
    return int(row[0])

def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {str(row[1]) for row in rows}

def validate_schema(conn: sqlite3.Connection) -> int:
    version = schema_version(conn)
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise SchemaMismatchError(f"unsupported Hermes schema_version {version}; supported: {sorted(SUPPORTED_SCHEMA_VERSIONS)}")
    missing_sessions = REQUIRED_SESSION_COLUMNS - _columns(conn, "sessions")
    missing_usage = REQUIRED_USAGE_COLUMNS - _columns(conn, "session_model_usage")
    if missing_sessions or missing_usage:
        raise SchemaMismatchError(f"sessions missing {sorted(missing_sessions)}; session_model_usage missing {sorted(missing_usage)}")
    return version

def fetch_usage_rows(conn: sqlite3.Connection, since: float = 0.0) -> list[dict[str, Any]]:
    validate_schema(conn)
    rows = [dict(r) for r in conn.execute(EXTRACTION_SQL, (float(since),)).fetchall()]
    rows.extend(dict(r) for r in conn.execute(LEGACY_RECONCILIATION_SQL, (float(since),)).fetchall())
    return rows

"""Delta and event-id generation for cumulative Hermes usage rows."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from .contract import (
    Observation,
    SNAPSHOT_FIELDS,
    cost_from_row,
    normalize_last_seen,
    normalize_model,
    normalize_provider,
    timestamp_iso,
)


def snapshot_from_row(row: Mapping[str, Any]) -> dict[str, float | int]:
    out = {}
    for key in SNAPSHOT_FIELDS:
        val = row.get(key) or 0
        out[key] = float(val) if key.endswith("_usd") else int(val)
    return out


def aggregate_key(row: Mapping[str, Any], profile: str, db_path: str | Path | None = None) -> str:
    payload = {
        "profile": profile,
        "db_path": str(Path(db_path).resolve()) if db_path else "",
        "session_id": str(row.get("session_id") or ""),
        "model": str(row.get("model") or ""),
        "billing_provider": str(row.get("billing_provider") or ""),
        "billing_base_url": str(row.get("billing_base_url") or ""),
        "billing_mode": str(row.get("billing_mode") or ""),
        "task": str(row.get("task") or ""),
        "legacy_residual": int(row.get("legacy_residual") or 0),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def event_id(key: str, last_seen: float | str, snapshot: Mapping[str, Any]) -> str:
    payload = {
        "aggregate_key": key,
        "last_seen": normalize_last_seen(last_seen),
        "snapshot": {k: snapshot.get(k, 0) for k in sorted(snapshot)},
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:48]


class WatermarkStore:
    """Sidecar-owned source snapshot history.

    The historical name is kept for compatibility with existing configuration and
    state-db paths, but this store is no longer an ingestion cursor. It records
    source aggregate snapshots by profile/key/last_seen so each API caller can use
    its own `since` cursor without another caller hiding rows globally.
    """

    def __init__(self, path: Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS watermarks("
            "profile TEXT NOT NULL, aggregate_key TEXT NOT NULL, last_seen TEXT NOT NULL, "
            "agg_json TEXT NOT NULL, PRIMARY KEY(profile, aggregate_key))"
        )
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS aggregate_snapshots("
            "profile TEXT NOT NULL, aggregate_key TEXT NOT NULL, last_seen TEXT NOT NULL, "
            "agg_json TEXT NOT NULL, PRIMARY KEY(profile, aggregate_key, last_seen))"
        )

    def close(self) -> None:
        self.conn.close()

    def get(self, profile: str, key: str) -> tuple[str, dict[str, Any]] | None:
        row = self.conn.execute(
            "SELECT last_seen, agg_json FROM watermarks WHERE profile=? AND aggregate_key=?",
            (profile, key),
        ).fetchone()
        return None if row is None else (str(row["last_seen"]), json.loads(row["agg_json"]))

    def set(self, profile: str, key: str, last_seen: float | str, snapshot: Mapping[str, Any]) -> None:
        normalized_last_seen = normalize_last_seen(last_seen)
        encoded_snapshot = json.dumps(dict(snapshot), sort_keys=True, separators=(",", ":"))
        self.conn.execute(
            "INSERT INTO watermarks(profile,aggregate_key,last_seen,agg_json) VALUES (?,?,?,?) "
            "ON CONFLICT(profile,aggregate_key) DO UPDATE SET "
            "last_seen=excluded.last_seen, agg_json=excluded.agg_json",
            (profile, key, normalized_last_seen, encoded_snapshot),
        )
        self.conn.execute(
            "INSERT INTO aggregate_snapshots(profile,aggregate_key,last_seen,agg_json) VALUES (?,?,?,?) "
            "ON CONFLICT(profile,aggregate_key,last_seen) DO UPDATE SET agg_json=excluded.agg_json",
            (profile, key, normalized_last_seen, encoded_snapshot),
        )

    def previous_snapshot(self, profile: str, key: str, last_seen: float | str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT agg_json FROM aggregate_snapshots "
            "WHERE profile=? AND aggregate_key=? AND CAST(last_seen AS REAL) < CAST(? AS REAL) "
            "ORDER BY CAST(last_seen AS REAL) DESC, last_seen DESC LIMIT 1",
            (profile, key, normalize_last_seen(last_seen)),
        ).fetchone()
        return None if row is None else json.loads(row["agg_json"])

    def snapshots_since(self, profile: str, key: str, since: float) -> list[tuple[str, dict[str, Any]]]:
        rows = self.conn.execute(
            "SELECT last_seen, agg_json FROM aggregate_snapshots "
            "WHERE profile=? AND aggregate_key=? AND CAST(last_seen AS REAL) > ? "
            "ORDER BY CAST(last_seen AS REAL), last_seen",
            (profile, key, float(since or 0)),
        ).fetchall()
        return [(str(row["last_seen"]), json.loads(row["agg_json"])) for row in rows]


def _delta_snapshot(now: Mapping[str, Any], previous: Mapping[str, Any] | None) -> dict[str, float | int]:
    previous = previous or {}
    out = {}
    for key, value in now.items():
        delta = float(value) - float(previous.get(key, 0) or 0)
        out[key] = max(0.0, delta) if key.endswith("_usd") else max(0, int(round(delta)))
    return out


def _has_usage(delta: Mapping[str, Any]) -> bool:
    return any(float(delta.get(k, 0) or 0) > 0 for k in SNAPSHOT_FIELDS)


def _observation_from_delta(
    row: Mapping[str, Any],
    profile: str,
    key: str,
    last_seen: float | str,
    snapshot: Mapping[str, Any],
    delta: Mapping[str, Any],
) -> Observation:
    cost_value, cost_type = cost_from_row({**row, **delta})
    return Observation(
        event_id=event_id(key, last_seen, snapshot),
        timestamp=timestamp_iso(last_seen),
        provider=normalize_provider(row.get("billing_provider")),
        model=normalize_model(row.get("model")),
        profile=profile,
        session_id=str(row.get("session_id") or ""),
        input_tokens=int(delta["input_tokens"]),
        output_tokens=int(delta["output_tokens"]),
        cache_read_tokens=int(delta["cache_read_tokens"]),
        cache_write_tokens=int(delta["cache_write_tokens"]),
        reasoning_tokens=int(delta["reasoning_tokens"]),
        requests=int(delta["api_call_count"]),
        cost=float(cost_value),
        cost_type=cost_type,
    )


def compute_deltas(rows: list[Mapping[str, Any]], store: WatermarkStore, profile: str, db_path: str | Path | None = None) -> list[Observation]:
    """Return deltas for current rows and record their snapshots.

    This legacy helper is intentionally unchanged semantically for unit tests and
    callers that only want newly observed source changes.
    """
    observations = []
    for row in rows:
        key = aggregate_key(row, profile, db_path)
        snap = snapshot_from_row(row)
        previous = store.get(profile, key)
        delta = _delta_snapshot(snap, previous[1] if previous else None)
        last_seen = row.get("last_seen") or 0
        store.set(profile, key, last_seen, snap)
        if not _has_usage(delta):
            continue
        observations.append(_observation_from_delta(row, profile, key, last_seen, snap, delta))
    return observations


def compute_observations_since(
    rows: list[Mapping[str, Any]],
    store: WatermarkStore,
    profile: str,
    since: float,
    db_path: str | Path | None = None,
) -> list[Observation]:
    """Return deterministic caller-cursor observations for source rows.

    The sidecar records source snapshots, but it does not mark them consumed.
    Repeating a request with the same `since` value returns the same observations;
    another consumer using `since=0` can still bootstrap from recorded/current
    history instead of being hidden by a previous API call.
    """
    observations = []
    for row in rows:
        key = aggregate_key(row, profile, db_path)
        current_last_seen = row.get("last_seen") or 0
        store.set(profile, key, current_last_seen, snapshot_from_row(row))
        for last_seen, snap in store.snapshots_since(profile, key, since):
            previous = store.previous_snapshot(profile, key, last_seen)
            delta = _delta_snapshot(snap, previous)
            if not _has_usage(delta):
                continue
            observations.append(_observation_from_delta(row, profile, key, last_seen, snap, delta))
    return observations

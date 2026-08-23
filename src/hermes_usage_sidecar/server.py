"""FastAPI application for the Hermes usage sidecar."""
from __future__ import annotations
import hmac
from typing import Any
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from .config import Settings
from .db import SchemaMismatchError, discover_profile_dbs, fetch_usage_rows, ro_connect, validate_schema
from .delta import WatermarkStore, compute_observations_since

def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="Hermes Usage Sidecar", version="0.1.0")
    store = WatermarkStore(settings.state_db)
    def require_auth(authorization: str | None = Header(default=None)) -> None:
        if not settings.token: return
        candidate = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        if not hmac.compare_digest(candidate, settings.token):
            raise HTTPException(status_code=401, detail="Unauthorized")
    @app.get("/healthz", dependencies=[Depends(require_auth)])
    def healthz() -> dict[str, Any]:
        profiles, versions, errors = [], {}, {}
        for pdb in discover_profile_dbs(settings.hermes_home):
            profiles.append(pdb.profile)
            try:
                conn = ro_connect(pdb.path)
                try: versions[pdb.profile] = validate_schema(conn)
                finally: conn.close()
            except Exception as exc:
                errors[pdb.profile] = str(exc)
        return {"ok": not errors, "profiles": profiles, "schema_versions": versions, "errors": errors}
    @app.get("/usage", dependencies=[Depends(require_auth)])
    def usage(since: float = Query(0.0), profile: str | None = None) -> dict[str, Any]:
        observations, max_watermark, errors = [], float(since or 0), {}
        dbs = discover_profile_dbs(settings.hermes_home)
        if profile: dbs = [db for db in dbs if db.profile == profile]
        for pdb in dbs:
            try:
                conn = ro_connect(pdb.path)
                try: rows = fetch_usage_rows(conn, since=since)
                finally: conn.close()
                for row in rows: max_watermark = max(max_watermark, float(row.get("last_seen") or 0))
                observations.extend(obs.to_dict() for obs in compute_observations_since(rows, store, pdb.profile, since, pdb.path))
            except SchemaMismatchError as exc:
                errors[pdb.profile] = str(exc)
        if errors:
            raise HTTPException(status_code=409, detail={"message":"Hermes DB schema compatibility error", "profiles": errors})
        return {"observations": observations, "watermark": max_watermark}
    return app

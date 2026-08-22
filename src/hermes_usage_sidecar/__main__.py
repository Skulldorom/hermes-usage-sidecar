"""CLI entrypoint."""
from __future__ import annotations
import json, sys
import uvicorn
from .config import parser, settings_from_args
from .db import SchemaMismatchError, discover_profile_dbs, fetch_usage_rows, ro_connect, validate_schema
from .server import create_app

def dump(settings) -> int:
    for pdb in discover_profile_dbs(settings.hermes_home):
        print(f"# profile={pdb.profile} path={pdb.path}")
        conn = ro_connect(pdb.path)
        try:
            print(f"schema_version={validate_schema(conn)}")
            for row in fetch_usage_rows(conn, since=0):
                keys = ("session_id","model","billing_provider","billing_mode","task","api_call_count","input_tokens","output_tokens","cache_read_tokens","cache_write_tokens","reasoning_tokens","estimated_cost_usd","actual_cost_usd","cost_status","last_seen","legacy_residual")
                print(json.dumps({k: row.get(k) for k in keys}, sort_keys=True))
        finally: conn.close()
    return 0

def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv); settings = settings_from_args(args)
    if args.dump:
        try: return dump(settings)
        except SchemaMismatchError as exc:
            print(f"compatibility error: {exc}", file=sys.stderr); return 2
    uvicorn.run(create_app(settings), host=settings.bind, port=settings.port)
    return 0
if __name__ == "__main__":
    raise SystemExit(main())

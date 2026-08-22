"""Configuration and CLI argument parsing."""
from __future__ import annotations
import argparse, os
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Settings:
    hermes_home: Path
    state_db: Path
    bind: str = "127.0.0.1"
    port: int = 8799
    token: str | None = None
    poll: int = 30

def default_state_db() -> Path:
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "hermes-usage-sidecar" / "state.db"

def read_token(token_file: str | None) -> str | None:
    if token_file:
        return Path(token_file).expanduser().read_text(encoding="utf-8").strip()
    token = os.environ.get("USAGE_SIDECAR_TOKEN")
    return token.strip() if token else None

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Read-only Hermes usage sidecar")
    p.add_argument("--hermes-home", default="~/.hermes")
    p.add_argument("--state-db", default=str(default_state_db()))
    p.add_argument("--bind", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8799)
    p.add_argument("--token-file")
    p.add_argument("--poll", type=int, default=30)
    p.add_argument("--dump", action="store_true")
    p.add_argument("--serve", action="store_true")
    return p

def settings_from_args(args: argparse.Namespace) -> Settings:
    return Settings(Path(args.hermes_home).expanduser(), Path(args.state_db).expanduser(), args.bind, args.port, read_token(args.token_file), args.poll)

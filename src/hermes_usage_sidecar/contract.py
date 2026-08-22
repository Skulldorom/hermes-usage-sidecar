"""Usage Dashboard observation contract helpers."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

SNAPSHOT_FIELDS = ("api_call_count","input_tokens","output_tokens","cache_read_tokens","cache_write_tokens","reasoning_tokens","estimated_cost_usd","actual_cost_usd")

@dataclass(frozen=True)
class Observation:
    event_id: str
    timestamp: str
    provider: str
    model: str
    profile: str
    session_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    requests: int = 0
    cost: float = 0.0
    cost_type: str = "unavailable"
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

def normalize_model(model: Any) -> str:
    value = str(model or "unknown").strip() or "unknown"
    if value.endswith(":free"):
        value = value[:-5]
    return value.rsplit("/", 1)[-1] if "/" in value else value

def normalize_provider(provider: Any) -> str:
    return str(provider or "unknown").strip().lower() or "unknown"

def normalize_last_seen(value: Any) -> str:
    numeric = float(value or 0)
    return (f"{numeric:.9f}".rstrip("0").rstrip(".")) or "0"

def timestamp_iso(value: Any) -> str:
    return datetime.fromtimestamp(float(value or 0), tz=timezone.utc).isoformat().replace("+00:00", "Z")

def cost_from_row(row: Mapping[str, Any]) -> tuple[float, str]:
    actual = float(row.get("actual_cost_usd") or 0.0)
    status = str(row.get("cost_status") or "").strip().lower()
    if actual > 0:
        return actual, "actual"
    if status == "included":
        return 0.0, "included"
    estimated = float(row.get("estimated_cost_usd") or 0.0)
    if status == "estimated" or estimated > 0:
        return estimated, "estimated"
    return 0.0, "unavailable"

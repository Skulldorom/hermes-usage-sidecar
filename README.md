# hermes-usage-sidecar

Standalone **read-only** Hermes Agent usage sidecar for Usage Dashboard.

## Scope

This is Architecture B only: a standalone sidecar. It does **not** modify or fork Hermes Agent and it does **not** implement the optional plugin.

## What it does

- Discovers `~/.hermes/state.db` as profile `default`.
- Discovers every `~/.hermes/profiles/*/state.db` automatically.
- Opens Hermes databases with SQLite `mode=ro` and `PRAGMA query_only=ON`.
- Reads aggregate usage metadata from `session_model_usage` and safe legacy residual counters from `sessions`.
- Never reads or exposes `messages` or conversation content.
- Stores sidecar-owned watermarks separately at `~/.local/state/hermes-usage-sidecar/state.db` by default.

## `/usage` contract

`GET /usage` returns the contract currently consumed by `Skulldorom/usage-dashboard`:

```json
{
  "observations": [
    {
      "event_id": "stable-source-event-id",
      "timestamp": "2026-08-22T12:00:00.123456Z",
      "provider": "anthropic",
      "model": "claude-sonnet-4",
      "profile": "coder",
      "session_id": "...",
      "input_tokens": 100,
      "output_tokens": 50,
      "cache_read_tokens": 0,
      "cache_write_tokens": 0,
      "reasoning_tokens": 0,
      "requests": 1,
      "cost": 0.0123,
      "cost_type": "estimated"
    }
  ],
  "watermark": 1770000000.123456
}
```

Observations are **deltas**, not cumulative snapshots. The deterministic `event_id` includes the aggregate identity, the full normalized sub-second Hermes `last_seen`, and the cumulative aggregate snapshot. It deliberately does not use `int(last_seen)`.

## Run

```bash
python3.10 -m pip install .
USAGE_SIDECAR_TOKEN='replace-me' hermes-usage-sidecar --hermes-home ~/.hermes --bind 127.0.0.1 --port 8799
```

Smoke dump:

```bash
hermes-usage-sidecar --dump --hermes-home ~/.hermes
```

## systemd user service (primary)

```bash
mkdir -p ~/.config/systemd/user
cp deploy/hermes-usage-sidecar.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now hermes-usage-sidecar.service
```

The unit binds to `127.0.0.1`, treats `~/.hermes` as read-only, and only grants write access to `~/.local/state/hermes-usage-sidecar` for watermarks.

## Docker (secondary)

```bash
docker build -t hermes-usage-sidecar .
docker run --rm -p 127.0.0.1:8799:8799 \
  -e USAGE_SIDECAR_TOKEN="$USAGE_SIDECAR_TOKEN" \
  -v "$HOME/.hermes:/hermes:ro" \
  -v "$HOME/.local/state/hermes-usage-sidecar:/state" \
  hermes-usage-sidecar
```

## Compatibility

Supports Hermes `state.db` schema versions 22 through 26, including current upstream Hermes Agent schema 26. Extra columns are tolerated. Unknown versions or missing/renamed usage columns return an explicit compatibility error instead of incorrect usage.

## Usage Dashboard setup

Configure a Hermes data source with:

- Base URL: `http://127.0.0.1:8799`
- Bearer token: the sidecar token
- Optional provider mappings as needed

Use one sidecar/data-source pair per Hermes installation.

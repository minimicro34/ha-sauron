"""Constants for the SAURon Home Assistant integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final[str] = "sauron"

# ── Config entry keys ─────────────────────────────────────────────────────────
CONF_LOGIN: Final[str] = "login"
CONF_PASSWORD: Final[str] = "password"
CONF_CLIENT_ID: Final[str] = "client_id"
CONF_SUBSCRIPTION_ID: Final[str] = "subscription_id"
CONF_TOKEN_CACHE: Final[str] = "_token_cache"
"""Internal key inside entry.data for persisted token. Underscore-prefixed
to mark it as integration-managed (not user input)."""

# ── Options keys ──────────────────────────────────────────────────────────────
OPT_SCAN_INTERVAL_H: Final[str] = "scan_interval_h"
OPT_STALE_DATA_THRESHOLD_H: Final[str] = "stale_data_threshold_h"

# ── Defaults ──────────────────────────────────────────────────────────────────
DEFAULT_SCAN_INTERVAL_H: Final[int] = 4
"""Poll every 4 hours — SAUR daily data is normally published with a delay."""

DEFAULT_STALE_DATA_THRESHOLD_H: Final[int] = 72
"""Raise a Repair Issue if the latest daily consumption is older than 72h."""

# ── Options bounds ────────────────────────────────────────────────────────────
OPT_SCAN_INTERVAL_H_MIN: Final[int] = 1
OPT_SCAN_INTERVAL_H_MAX: Final[int] = 24
OPT_STALE_DATA_THRESHOLD_H_MIN: Final[int] = 12
OPT_STALE_DATA_THRESHOLD_H_MAX: Final[int] = 96

# ── Repair issue identifiers ─────────────────────────────────────────────────
ISSUE_STALE_DATA: Final[str] = "stale_data"

# ── Token lifecycle (Plan A) ──────────────────────────────────────────────────
DEFAULT_TOKEN_TTL_S: Final[int] = 3600
"""Fallback token lifetime when SAUR auth response omits ``expires_in``.
The two-tier 401 retry in the client absorbs a wrong guess transparently."""

TOKEN_REFRESH_MARGIN_S: Final[int] = 300
"""Refresh the token this many seconds before it actually expires.
Also absorbs reasonable host-vs-server clock skew."""

HASS_DATA_OPTIONS_SNAPSHOT: Final[str] = "options_snapshot"
"""Suffix for the per-entry options snapshot stored in hass.data — used by
the update listener to ignore data-only updates (token cache writes)."""

# Plan A — Token persistence & expiry-aware refresh for SAURon (v2)

> **Status:** v2 — integrates reviewer feedback (RC‑1…RC‑4 + nice‑to‑haves).
> **Goal:** stop Home Assistant from regularly asking the user to re-enter login / password.
> **Root cause (recap):** the SAUR bearer token is RAM-only (`client.py:54`), every HA restart re-authenticates; any 401/403 that bubbles up is treated indiscriminately as "bad credentials" and triggers `ConfigEntryAuthFailed` → reauth banner.
> **Strategy:** persist the token across restarts, refresh it *before* it expires, and only treat **confirmed** auth failures as reauth-worthy.
>
> **Changes vs v1:**
> - § 3.5 rewritten to guard `_async_update_listener` against `data`-only updates (RC‑1).
> - § 3.2 / § 3.3 mandate `asyncio.Lock` in this PR, not deferred (RC‑2).
> - § 3.6 fixes the monthly bare‑except (RC‑3, pre‑existing silent‑swallow bug).
> - § 4 adds 4 coordinator‑level tests for exception mapping (RC‑4) + 1 lock test.
> - `_TokenCache` renamed `TokenCache` (public) — nice‑to‑have.
> - `pyproject.toml` coverage source widened — nice‑to‑have.
> - § 6 telemetry promoted from "optional" to "mandatory step 0" (A1 confirmed Low).

---

## 1. Classification

- **Type:** bug fix + small feature (cache + lifecycle).
- **Scope:** `custom_components/sauron/api/client.py`, `custom_components/sauron/api/exceptions.py`, `custom_components/sauron/api/__init__.py`, `custom_components/sauron/coordinator.py`, `custom_components/sauron/__init__.py`, `custom_components/sauron/const.py`, `pyproject.toml`, tests.
- **Risk:** Medium — touches the auth path, the most user-visible failure mode of the integration.

## 2. Declared assumptions (v2 — re‑validated by reviewer)

| # | Assumption | Source | Confidence | Action |
|---|---|---|---|---|
| A1 | `/admin/v2/auth` returns `expires_in` | OAuth convention, but **absent from observed response shape** (test fixture `_AUTH_SUCCESS`, comment `client.py:60-68`) | **Low — confirmed by reviewer** | **Mandatory step 0 telemetry** before relying on it — see §0 |
| A2 | Token lifetime ≥ 1h | Circumstantial (Saur_fr_client behavior) | **Medium** | Telemetry §0 confirms |
| A3 | No `refresh_token` dependency | Confirmed: `client.py` never reads one | **High** | None |
| A4 | `entry.data` is acceptable for token persistence | Confirmed: password already there in clear | **High** | None |
| A5 | 401/403 on non-auth endpoints can mean expired token | Confirmed in `client.py:121-147` | **High** | None |
| A6 | Network / 5xx must yield `UpdateFailed`, not `ConfigEntryAuthFailed` | HA dev docs | **High** | Plan enforces with `SauronTransientError` |

## 0. Mandatory step 0 — telemetry probe (1 release, 1 line)

Before the structural changes, ship **one debug log line** in `async_authenticate()`:

```python
_LOGGER.debug("SAUR auth response keys=%s expires_in=%s", list(data.keys()), data.get("expires_in"))
```

Run for one auth cycle, observe in `home-assistant.log`. Two outcomes:
- `expires_in` present → use it everywhere. Plan proceeds as written.
- `expires_in` absent → keep `DEFAULT_TOKEN_TTL_S = 3600` fallback; document the choice in the PR.

This is a no‑op behavior change and can ship in the same PR — it just precedes the rest of the work in the commit order.

## 3. Design

### 3.1 New `TokenCache` value object (in `api/client.py`, exported via `api/__init__.py`)

```python
@dataclass(frozen=True, slots=True)
class TokenCache:
    access_token: str
    expires_at: float  # epoch seconds (time.time())
    client_id: str
    default_section_id: str
```

- Public name (no leading underscore) — exported from `api/__init__.py` so `__init__.py` can type‑hint the persistence callback under mypy `strict`.
- `frozen=True` to prevent accidental mutation; replaced wholesale on refresh.

### 3.2 Client lifecycle changes

`SauronApiClient.__init__` gains:

```python
def __init__(
    self,
    session: aiohttp.ClientSession,
    login: str,
    password: str,
    *,
    initial_token: TokenCache | None = None,
    on_token_refreshed: Callable[[TokenCache], Awaitable[None]] | None = None,
) -> None:
    self._session = session
    self._login = login
    self._password = password
    self._cache: TokenCache | None = initial_token
    self._on_token_refreshed = on_token_refreshed
    self._auth_lock: asyncio.Lock = asyncio.Lock()  # ← RC‑2: now, not deferred
```

`_is_token_valid()` becomes expiry‑aware:

```python
def _is_token_valid(self) -> bool:
    return self._cache is not None and time.time() < self._cache.expires_at - TOKEN_REFRESH_MARGIN_S
```

`_ensure_token()` — **double‑checked pattern under `asyncio.Lock`** (RC‑2):

```python
async def _ensure_token(self) -> str:
    if self._is_token_valid():
        assert self._cache is not None
        return self._cache.access_token

    async with self._auth_lock:
        # Re-check under lock: another task may have authenticated while we waited
        if self._is_token_valid():
            assert self._cache is not None
            return self._cache.access_token
        await self.async_authenticate()

    assert self._cache is not None
    return self._cache.access_token
```

`async_authenticate()` now builds a `TokenCache`, reads `expires_in` (fallback `DEFAULT_TOKEN_TTL_S`), and awaits `on_token_refreshed`:

```python
async def async_authenticate(self) -> None:
    # ... existing POST logic unchanged ...
    token_obj = data.get("token") or {}
    access_token = token_obj.get("access_token") if isinstance(token_obj, dict) else None
    if not access_token:
        raise SauronAuthError("No access_token in auth response")

    ttl_s = int(data.get("expires_in") or DEFAULT_TOKEN_TTL_S)
    self._cache = TokenCache(
        access_token=access_token,
        expires_at=time.time() + ttl_s,
        client_id=str(data.get("clientId", "")),
        default_section_id=str(data.get("defaultSectionId", "")),
    )
    if self._on_token_refreshed is not None:
        await self._on_token_refreshed(self._cache)
    _LOGGER.debug(
        "SAUR authenticated: client_id=%s, default_section_id=%s, ttl_s=%d",
        self._cache.client_id,
        self._cache.default_section_id,
        ttl_s,
    )
```

`client_id` and `default_section_id` properties read from `self._cache` (return `None` when not authenticated).

### 3.3 Two-tier 401/403 handling in `_get()` (with proper transient classification)

```python
async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
    token = await self._ensure_token()
    status, body = await self._do_get(path, token, params)

    if status not in (401, 403):
        return body  # success path; _do_get already raised for non-200/4xx auth

    # First 401/403 — assume token expired or transient. Force re-auth & retry once.
    _LOGGER.debug("Token rejected (%d) on %s — refreshing", status, path)
    self._cache = None
    try:
        await self.async_authenticate()
    except SauronAuthError:
        # Auth endpoint itself rejected → credentials really are bad.
        raise
    except SauronApiError as err:
        # Auth endpoint is down (5xx) → transient, not a credentials problem.
        raise SauronTransientError(f"Auth refresh failed: {err}") from err

    assert self._cache is not None
    status2, body2 = await self._do_get(path, self._cache.access_token, params)
    if status2 in (401, 403):
        # Fresh token rejected → credentials really are dead.
        raise SauronAuthError(f"Endpoint {path} rejected fresh token")
    return body2
```

`_do_get(path, token, params) -> tuple[int, Any]`:
- Returns `(status, parsed_json_or_None)` for 200, 401, 403.
- Raises `SauronApiError(status, body_text)` for any other non-2xx.
- Raises `SauronTransientError` on `aiohttp.ClientError` / `asyncio.TimeoutError`.

### 3.4 New exception type — `SauronTransientError`

Added to `api/exceptions.py`:

```python
class SauronTransientError(SauronError):
    """Temporary failure (network, 5xx, auth endpoint flaky). Retry later, do NOT reauth."""
```

Exported via `api/__init__.py` alongside the existing exceptions.

### 3.5 Persistence wiring — RC‑1 fix (reload guard)

**Bug to avoid:** `_async_update_listener` (`__init__.py:55-57`) calls `async_reload` on **any** entry update, including `data` writes. Without a guard, every token refresh (~hourly) would tear down and rebuild the coordinator.

**Fix:** snapshot the *options* at setup; in the listener, reload only if options changed; ignore `data`-only updates (token cache writes).

```python
# const.py — new
HASS_DATA_OPTIONS_SNAPSHOT: Final[str] = "options_snapshot"


# __init__.py
async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    session = async_get_clientsession(hass)

    cached = _hydrate_token_from_entry(entry)

    async def _persist_token(cache: TokenCache) -> None:
        # Writes to entry.data; the update listener guards against reload (see below).
        new_data = {**entry.data, CONF_TOKEN_CACHE: asdict(cache)}
        hass.config_entries.async_update_entry(entry, data=new_data)

    client = SauronApiClient(
        session=session,
        login=entry.data[CONF_LOGIN],
        password=entry.data[CONF_PASSWORD],
        initial_token=cached,
        on_token_refreshed=_persist_token,
    )

    coordinator = SauronCoordinator(hass, client, entry)
    await coordinator.async_setup()
    await coordinator.async_config_entry_first_refresh()

    domain_data = hass.data.setdefault(DOMAIN, {})
    domain_data[entry.entry_id] = coordinator
    # Snapshot options for the reload-guard
    domain_data[f"{entry.entry_id}_{HASS_DATA_OPTIONS_SNAPSHOT}"] = dict(entry.options)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload only when *options* changed — ignore data-only updates (token cache)."""
    domain_data = hass.data.get(DOMAIN, {})
    snapshot_key = f"{entry.entry_id}_{HASS_DATA_OPTIONS_SNAPSHOT}"
    old_options = domain_data.get(snapshot_key, {})
    new_options = dict(entry.options)
    if new_options == old_options:
        return  # data-only update (token cache) → no reload
    domain_data[snapshot_key] = new_options
    await hass.config_entries.async_reload(entry.entry_id)


def _hydrate_token_from_entry(entry: ConfigEntry) -> TokenCache | None:
    raw = entry.data.get(CONF_TOKEN_CACHE)
    if not isinstance(raw, dict):
        return None
    try:
        cache = TokenCache(
            access_token=str(raw["access_token"]),
            expires_at=float(raw["expires_at"]),
            client_id=str(raw["client_id"]),
            default_section_id=str(raw["default_section_id"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if time.time() >= cache.expires_at - TOKEN_REFRESH_MARGIN_S:
        return None  # already (near) expired — let the client re-auth
    return cache


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        domain_data = hass.data.get(DOMAIN, {})
        domain_data.pop(entry.entry_id, None)
        domain_data.pop(f"{entry.entry_id}_{HASS_DATA_OPTIONS_SNAPSHOT}", None)
    return unloaded
```

**Why this resolves RC‑1:** comparing options dicts only, `data` mutations (token refresh) are filtered out at the listener boundary. The snapshot lives in `hass.data` and is rebuilt at every setup, so it survives reloads cleanly.

### 3.6 Coordinator changes — RC‑3 fix (monthly bare-except)

Replace the three `except` clauses in `_async_update_data`:

```python
# Block 1 — last meter index (mandatory data path) — coordinator.py:79-87
except SauronAuthError as err:
    raise ConfigEntryAuthFailed from err
except SauronTransientError as err:
    raise UpdateFailed(f"SAUR API transient error: {err}") from err
except SauronNoDataError as err:
    _LOGGER.warning("Unexpected SAUR payload for %s: %s", subscription_id, err)
    raise UpdateFailed(f"SAUR payload error: {err}") from err
except Exception as err:
    raise UpdateFailed(f"SAUR API error: {err}") from err

# Block 2 — monthly (enrichment) — RC‑3: was silently swallowed
except SauronAuthError as err:
    raise ConfigEntryAuthFailed from err
except SauronTransientError as err:
    # Enrichment is non-fatal: log and continue with primary data only.
    _LOGGER.warning("SAUR monthly transient: %s — skipping enrichment", err)
    raw_monthly = {}
except Exception as err:
    _LOGGER.warning("Could not fetch monthly data for %s: %s", subscription_id, err)
    raw_monthly = {}

# Block 3 — yearly (enrichment) — same pattern as Block 2
except SauronAuthError as err:
    raise ConfigEntryAuthFailed from err
except SauronTransientError as err:
    _LOGGER.debug("SAUR yearly transient: %s — skipping yearly enrichment", err)
except Exception as err:
    _LOGGER.debug("Could not fetch yearly data for %s: %s", subscription_id, err)
```

**Behavioral contract:**
- **Primary endpoint failure (Block 1):** any auth failure → reauth banner; any transient → yellow `UpdateFailed`; any payload shape issue → yellow `UpdateFailed`.
- **Enrichment endpoints (Blocks 2, 3):** auth failure still bubbles up (was silently swallowed before — fixing the latent RC‑3 bug); transient is logged and the enrichment field stays `None` so the user keeps their primary reading.

### 3.7 Constants

Add to `const.py`:

```python
CONF_TOKEN_CACHE: Final[str] = "_token_cache"  # underscore prefix = internal data
DEFAULT_TOKEN_TTL_S: Final[int] = 3600  # fallback when expires_in absent
TOKEN_REFRESH_MARGIN_S: Final[int] = 300  # refresh 5 min early (clock-skew margin)
HASS_DATA_OPTIONS_SNAPSHOT: Final[str] = "options_snapshot"  # reload-guard key suffix
```

### 3.8 Coverage source widening — nice‑to‑have

`pyproject.toml`:
```toml
[tool.coverage.run]
source = [
    "custom_components.sauron.api",
    "custom_components.sauron.coordinator",
    "custom_components.sauron",   # __init__.py
]
omit = [
    "custom_components/sauron/sensor.py",   # entity layer, light shim
    "custom_components/sauron/entity.py",   # entity layer, light shim
]
```

The omit list keeps the `fail_under = 80` realistic — the entity layer is harder to unit‑test and is best covered by integration tests in HA core, not here.

## 4. Test strategy

### 4.1 `tests/api/test_client.py` — new tests (additive, existing pass unchanged)

| Test | Asserts |
|---|---|
| `test_authenticate_reads_expires_in` | `client._cache.expires_at ≈ time.time() + 7200` when response includes `expires_in: 7200` |
| `test_authenticate_uses_default_ttl_when_missing` | fallback to `DEFAULT_TOKEN_TTL_S` when `expires_in` absent |
| `test_authenticate_invokes_on_token_refreshed` | callback awaited once with the new `TokenCache` |
| `test_is_token_valid_false_near_expiry` | `expires_at = now + 100` (< margin 300) → `False` |
| `test_is_token_valid_true_well_before_expiry` | `expires_at = now + 3600` → `True` |
| `test_initial_token_skips_first_auth_call` | constructor with `initial_token` → first `_get` issues 0 POSTs to `/auth` |
| `test_initial_token_expired_triggers_auth` | constructor with already-expired `TokenCache` → next `_get` re-authenticates |
| `test_get_401_then_success_returns_body` | happy retry path |
| `test_get_401_then_fresh_token_401_raises_auth_error` | confirms "fresh token also rejected" path |
| `test_get_401_then_auth_endpoint_500_raises_transient` | auth endpoint flaky → `SauronTransientError`, NOT `SauronAuthError` |
| `test_concurrent_ensure_token_authenticates_once` | **(RC‑2)** two `asyncio.gather`-ed `_ensure_token` calls with stale cache → exactly one `POST /auth` issued |

### 4.2 `tests/test_init_token_cache.py` — new file (HA layer)

Uses `pytest-homeassistant-custom-component` fixtures (`hass`, `MockConfigEntry`, `enable_custom_integrations`).

| Test | Asserts |
|---|---|
| `test_hydrates_token_from_entry_on_setup` | entry pre-populated with valid `_token_cache` → client constructed with `initial_token` non‑None → no auth POST during setup |
| `test_expired_cache_in_entry_is_ignored` | entry has `_token_cache.expires_at` in the past → client re-authenticates on first poll |
| `test_malformed_cache_in_entry_is_ignored` | `_token_cache = "garbage"` → silently treated as missing, no crash |
| `test_persist_token_writes_back_to_entry` | force a token refresh; `entry.data[CONF_TOKEN_CACHE]` is updated with the new fields |
| `test_token_update_does_not_reload_entry` | **(RC‑1)** force a token refresh; `hass.config_entries.async_reload` is **not** called; coordinator stays the same instance |
| `test_options_change_does_reload_entry` | mutate `entry.options[OPT_SCAN_INTERVAL_H]` → reload is called once |

### 4.3 `tests/test_coordinator_exception_mapping.py` — new file (RC‑4)

Uses a fake `SauronApiClient` that raises the desired exception per method.

| Test | Asserts |
|---|---|
| `test_auth_error_on_primary_raises_config_entry_auth_failed` | client raises `SauronAuthError` from `async_get_meter_last_index` → `_async_update_data` raises `ConfigEntryAuthFailed` |
| `test_transient_error_on_primary_raises_update_failed` | client raises `SauronTransientError` → `UpdateFailed` (not `ConfigEntryAuthFailed`) |
| `test_auth_error_on_monthly_raises_config_entry_auth_failed` | **(RC‑3)** client raises `SauronAuthError` from `async_get_monthly` → `ConfigEntryAuthFailed` (was silently swallowed before) |
| `test_transient_error_on_monthly_keeps_primary_data` | client raises `SauronTransientError` from `async_get_monthly` → coordinator returns primary data with `daily_liters = monthly_m3 = weekly_m3 = None` |

### 4.4 Existing tests — backward compat

- `tests/api/test_client.py::test_authenticate_success` etc. still pass — they don't pass `expires_in`, so we get the `DEFAULT_TOKEN_TTL_S` fallback. `client._token` direct access is replaced with `client._cache.access_token` (one‑line change).
- `tests/test_coordinator_parse.py` untouched (pure parse functions).

## 5. Migration / backward compat

- No CDS / schema migration. `entry.data[CONF_TOKEN_CACHE]` is purely additive.
- `async_migrate_entry` stays a no-op.
- Users upgrading from current version auth once, then never again until token genuinely expires or credentials change.

## 6. Rollout

Single PR, single commit chain:

1. `feat(api): add expires_in telemetry log` (1‑line step 0, ships as part of the PR)
2. `feat(api): introduce TokenCache + asyncio.Lock + transient errors`
3. `fix(coordinator): map transient & auth errors on all three endpoint calls`
4. `feat(init): persist token cache via callback, guard reload listener`
5. `test: client, coordinator-mapping, init-persistence + lock concurrency`
6. `chore(pyproject): widen coverage source to coordinator + init`

Each commit is independently green — facilitates `git bisect` if a regression slips in.

## 7. Out of scope (explicitly deferred)

- Using `refresh_token` (not confirmed to be emitted).
- Rate‑limit / exponential backoff on `/auth`.
- `aiohttp_retry` / `tenacity` dependency.
- reCAPTCHA hardening.
- Diagnostics platform / Silver-tier HACS items.

## 8. Risks (post‑RC fixes) & open questions

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `expires_in` absent → 3600s fallback marginally wrong | High | Low | Two‑tier 401 retry absorbs it transparently |
| Concurrent `_ensure_token` double‑auths | Medium → **Low** after RC‑2 | Low | `asyncio.Lock` + double‑checked pattern |
| Reload loop on token write | High → **0** after RC‑1 | High | Options‑diff guard in listener |
| `SauronAuthError` silently swallowed on enrichment | Medium → **0** after RC‑3 | Medium | New `except SauronAuthError` blocks 2 & 3 |
| Persisted token leaks via diagnostics dump | Low | Medium | No diagnostics platform implemented (out of scope) |
| Clock skew on `expires_at` | Low | Low | `TOKEN_REFRESH_MARGIN_S = 300` absorbs ≤ 5 min |
| `pytest-homeassistant-custom-component` not in dev deps | Low | Low (CI) | Confirm in `requirements_test.txt` or `pyproject` before writing 4.2 tests; if absent, add as dev‑only |

## 9. Acceptance criteria

- After a fresh setup, no `POST /admin/v2/auth` is observed for at least `expires_in − TOKEN_REFRESH_MARGIN_S` seconds of activity.
- After `homeassistant restart`, the first sensor refresh issues zero `POST /admin/v2/auth` if the cached token is still valid.
- A 401 on a non‑auth endpoint refreshes the token transparently — no user banner.
- Sustained 5xx on `/auth` yields a yellow "Update failed" notice, never a red "reauth required" one.
- The monthly enrichment failing with auth error correctly triggers `ConfigEntryAuthFailed` (previously silent).
- All existing tests pass; the 17 new tests above pass; coverage on `client.py`, `coordinator.py`, `__init__.py` each ≥ 80%.

## 10. Reviewer sign‑off matrix

| ID | Fix | Where | Status in v2 |
|----|-----|-------|--------------|
| RC‑1 | Reload guard on token write | `__init__.py:55-57` + new snapshot in `hass.data` | ✅ §3.5 |
| RC‑2 | `asyncio.Lock` included in this PR | `client.py:_ensure_token` | ✅ §3.2 |
| RC‑3 | Monthly bare‑except now handles auth + transient | `coordinator.py:110-113` (+ yearly 124) | ✅ §3.6 |
| RC‑4 | Coordinator exception‑mapping tests | `tests/test_coordinator_exception_mapping.py` | ✅ §4.3 |
| nice‑1 | `TokenCache` public + exported | `api/client.py`, `api/__init__.py` | ✅ §3.1 |
| nice‑2 | Coverage source widened | `pyproject.toml` | ✅ §3.8 |
| (new) | Telemetry probe mandatory (A1 Low) | `client.py:async_authenticate` | ✅ §0 |

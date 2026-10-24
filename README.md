# SAURon — Home Assistant integration for SAUR water consumption

> Monitor your SAUR water meter in Home Assistant with daily, weekly, monthly and yearly consumption, plus a reconstructed cumulative index for the Energy Dashboard.

<p align="center">

[![GitHub Release](https://img.shields.io/github/v/release/minimicro34/ha-sauron)](https://github.com/minimicro34/ha-sauron/releases)
[![Validate](https://github.com/minimicro34/ha-sauron/actions/workflows/validate.yml/badge.svg)](https://github.com/minimicro34/ha-sauron/actions/workflows/validate.yml)
[![HACS](https://img.shields.io/badge/HACS-Custom-blue.svg)](https://hacs.xyz/)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.12%2B-41BDF5.svg)](https://www.home-assistant.io/)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-☕-FFDD00?logo=buymeacoffee&logoColor=000000)](https://buymeacoffee.com/minimicro34)
[![License](https://img.shields.io/github/license/minimicro34/ha-sauron)](LICENSE)

</p>

💧 Daily usage • 📅 Weekly / monthly / yearly totals • 🔢 Estimated cumulative index • 📈 Dated Recorder statistics

---

SAURon is a custom Home Assistant integration for customers of the **SAUR** water service.

It retrieves the consumption data exposed by the SAUR customer API and provides native Home Assistant sensors. Because SAUR's physical meter index may only be refreshed when an official reading is performed, SAURon also reconstructs an estimated cumulative index from the latest physical reading and the daily consumption data published afterwards.

## Features

- **6 primary sensor entities** per meter subscription:

| Entity | Unit | Description |
|---|---|---|
| Estimated water index | m³ | Physical reading + daily consumption since that reading; recommended for Energy Dashboard → Water |
| Latest daily consumption | L | Most recent non-zero daily value actually published by SAUR |
| Weekly consumption | m³ | Current week total reported by SAUR |
| Previous week consumption | m³ | Previous completed ISO week, including delayed daily publication |
| Monthly consumption | m³ | Current month total reported by SAUR |
| Yearly consumption | m³ | Current year total reported by SAUR |

- **10 diagnostic sensor entities**, grouped by Home Assistant in the device's **Diagnostic** section:

| Diagnostic entity | Unit | Description |
|---|---|---|
| Water index | m³ | Latest physical meter reading reported by SAUR |
| Last reading date | date | Date of the latest physical SAUR reading |
| Latest daily consumption date | date | Date corresponding to the latest non-zero daily value published by SAUR |
| Data age | h | Hours since the date of the latest daily consumption actually published by SAUR |
| Last successful poll | timestamp | Timestamp of the latest successful coordinator refresh |
| Meter serial number | — | Physical meter serial number |
| Meter manufacturer | — | Meter manufacturer reported by SAUR |
| Meter model | — | Meter model reported by SAUR |
| Meter diameter | — | Meter diameter reported by SAUR |
| Remote reading technology | — | SAUR remote-reading technology |

- **Energy Dashboard compatible** — automatic dated Recorder statistics provide historical daily water consumption; the `Estimated water index` remains available as a separate cumulative sensor.
- **Automatic rebasing** — when SAUR publishes a new physical meter reading, it becomes the new baseline automatically.
- **Historical reconstruction** — daily entries from each required month are accumulated after the physical reading date.
- **Transient-server retry** — monthly HTTP 500 responses are retried once after 2 seconds; persistent failures preserve the previous estimate and back off at 2, 5 and then 10 minutes.
- **Last-value preservation** — a temporary historical-month failure keeps the last valid estimated index instead of replacing it with an incomplete value.
- **Re-authentication flow** — credentials can be updated without removing the integration.
- **Repair Issues** — Home Assistant warns when the latest published daily consumption becomes stale.
- **Options flow** — polling interval and stale-data threshold can be configured at runtime.
- **Multi-account** — multiple SAUR subscriptions can be configured.
- **Localised** — English, French, German and Spanish.

---

## Requirements

- Home Assistant **2024.12.0** or later
- A [SAUR customer portal](https://mon-espace.saurclient.fr) account (email + password)
- A meter with consumption data available through the SAUR customer service

---

## Installation

### Via HACS (recommended)

1. Open HACS in Home Assistant.
2. Open **⋮ → Custom repositories**.
3. Add `https://github.com/minimicro34/ha-sauron` as an **Integration** repository.
4. Search for **SAURon** and install it.
5. Restart Home Assistant.

### Manual

1. Copy `custom_components/sauron/` to your Home Assistant `config/custom_components/` directory.
2. Restart Home Assistant.

---

## Configuration

1. Go to **Settings → Devices & services → Add Integration**.
2. Search for **SAURon**.
3. Enter the credentials used on the SAUR customer portal.
4. SAURon discovers the subscription and water meter information automatically.

### Options

| Option | Default | Description |
|---|---:|---|
| Polling interval | 4 h | How often SAURon refreshes the SAUR API |
| Stale data threshold | 72 h | Age of the latest published daily consumption at which Home Assistant raises a Repair Issue |

SAUR generally publishes consumption data once per day, sometimes with a delay and potentially later after a weekend. A 72-hour default stale threshold avoids treating ordinary publication delays as an integration failure. Existing user-configured thresholds are preserved. Temporary HTTP 5xx failures affecting estimated-index reconstruction use a separate short retry sequence of 2, 5 and 10 minutes.

---

## Estimated water index

The physical **Water index** is kept unchanged and always represents the latest official index returned by SAUR.

The **Estimated water index** is calculated as:

```text
latest physical SAUR index
+ daily consumption strictly after the physical reading date
= estimated cumulative water index
```

For example, if SAUR reports a physical reading of `315.000 m³` on May 28, SAURon retrieves the daily consumption entries after May 28 and adds them to that baseline.

When a later technician reading is published, SAURon automatically discards the previous reconstruction baseline and starts again from the new physical reading. The reading day itself is excluded from the accumulated consumption to avoid double counting.

If a required historical monthly request returns HTTP 500, SAURon retries it once after 2 seconds. A successful retry restores the normal flow; if the request still fails, SAURon keeps the last valid estimated index and refreshes after 2 minutes, then 5 minutes, then every 10 minutes until recovery. The first HTTP 500 is logged at DEBUG, successful recovery at INFO and persistent failure at WARNING. Normal polling is restored automatically after recovery.

---

## Energy Dashboard

SAURon automatically publishes a separate dated Recorder water statistic:

`sauron:daily_water_<config_entry_id>`

This statistic is enabled by default and does not require an integration option. It is built from SAUR's daily consumption values, with a persistent daily ledger that preserves cumulative totals across physical meter readings and Home Assistant restarts. A rolling historical overlap allows late-published or corrected daily readings to update their original dates. Incomplete daily histories or failed monthly requests postpone imports rather than publishing partial totals. Unchanged histories do not trigger duplicate imports.

Each daily volume is timestamped at **23:00 in the Home Assistant local timezone** so it appears on the corresponding consumption day in the Energy Dashboard. The value is converted to UTC for Recorder storage. A daily reading of 0.81 m³ for October 14 therefore appears on October 14, not October 15.

To use the historical daily water data:

1. Go to **Settings → Energy**.
2. Under **Water**, choose **Add water source**.
3. Select **SAURon dated water** (the `sauron:daily_water_...` statistic).
4. Save. Historical consumption is then displayed on its original dates.

The **Estimated water index** sensor remains available as a separate, reconstructed cumulative reading. Do not configure both the dated statistic and the estimated index as independent water sources for the same meter, or consumption may be counted twice.

### Historical consumption tools (v0.6.3)

SAURon exposes maintenance actions in **Developer Tools → Actions**. These are intentionally separate from the integration's normal configuration, because importing or repairing historical Recorder data is an exceptional operation.

| Action | Purpose | Changes Recorder? |
|---|---|---|
| `sauron.preview_historical` | Inspect up to 36 days of SAUR daily readings | No |
| `sauron.preview_historical_coverage` | Audit up to 36 calendar months, including gaps and ledger overlap | No |
| `sauron.import_historical` | Guarded import of older daily readings contiguous with the existing ledger | Yes, after explicit confirmation and preflight; historical and existing cumulative sums are rebased together |
| `sauron.repair_historical_baseline` | Inspect and correct the negative cumulative baseline left by an earlier beta import | Only with `confirm: true` |

**Safety:** Keep a full Home Assistant backup before any write. Never rerun a confirmed import or baseline repair because an asynchronous action reports `queued`. The repair action supports a read-only preview and a subsequent read-only verification; a successful verification returns `status: verified`. The correction shifts cumulative sums without changing daily consumption states, and SAURon preserves the verified offset on later statistics publications.

Example of a **read-only** baseline repair inspection (replace the entry ID):

```yaml
action: sauron.repair_historical_baseline
data:
  entry_id: YOUR_CONFIG_ENTRY_ID
  confirm: false
```

**Release validation (v0.6.3):** 243 automated tests passed with 93.57% coverage; Python quality, HACS and hassfest passed in [CI run #39435353943](https://github.com/minimicro34/ha-sauron/actions/runs/39435353943). Regression coverage includes interrupted imports, partial Recorder writes, repeated verification, and publication resumption. The first positive import still requires validation against a fresh real Recorder database.

Historical coverage may contain unavailable SAUR dates. Missing dates are never silently invented as zero consumption. A confirmed import queues one Recorder task containing both the positive historical sums and the rebased existing sums; verify completion with the read-only `sauron.repair_historical_baseline` action before automatic publication resumes.

### `utility_meter` (optional)

You can create additional resettable counters from the estimated cumulative index:

```yaml
utility_meter:
  water_daily:
    source: sensor.saur_water_meter_estimated_water_index
    cycle: daily
  water_monthly:
    source: sensor.saur_water_meter_estimated_water_index
    cycle: monthly
```

Entity IDs may differ depending on the language in which the entities were first created. Check **Developer Tools → States** before copying an entity ID into YAML.

---

## SAURon Lovelace card

SAURon includes a built-in Home Assistant dashboard card. No third-party Lovelace cards are required. The card discovers the integration's entities and uses the dated Recorder statistics for its consumption chart.

Add a **Manual** card to your dashboard with:

```yaml
type: custom:sauron-card
mode: detailed
days: 7
show_chart: true
show_diagnostics: true
```

The card displays the latest daily consumption, weekly/monthly/yearly totals, estimated and physical indexes, and an interactive consumption chart. Switch between **7, 30 and 90 days** directly from the card. Hover over a bar (or tap it on a touchscreen) to display the date and consumption immediately.

The expandable **Information and diagnostics** panel groups data freshness, meter details, and remote-reading technology. The layout adapts to narrow mobile dashboards.

### Card options

| Option | Default | Description |
|---|---|---|
| `mode` | `detailed` | `detailed` shows indexes and diagnostics; `compact` shows summary metrics and the chart |
| `days` | `7` | Initial chart period: `7`, `30`, or `90` |
| `show_chart` | `true` | Display the historical consumption chart |
| `show_diagnostics` | `true` | Display the expandable diagnostics in detailed mode |
| `entry_id` | Automatic | Optional Home Assistant config entry ID when multiple SAURon subscriptions exist |

The card's frontend resource is registered automatically by the integration. Restart Home Assistant after installing or updating SAURon so the resource version is refreshed.

### Screenshots

Screenshots of the overview, 7-day, 30-day and 90-day views, and the expanded diagnostics will be added before the v1.0.0 release.

---

## Data freshness

SAUR generally publishes daily consumption data with a delay. The most recent available day is therefore not guaranteed to be yesterday. The physical meter index can remain unchanged for much longer because it corresponds to an official meter reading rather than the daily consumption feed.

The **Latest daily consumption** sensor deliberately shows the latest non-zero daily value actually available from SAUR, and the **Latest daily consumption date** diagnostic sensor shows which day that value belongs to. This prevents a delayed value from being presented as J−1.

The **Data age** diagnostic is calculated from that daily-consumption date and is also the value used by the stale-data Repair Issue. The separate **Last successful poll** timestamp reports when SAUron last completed a successful coordinator refresh. Together these distinguish delayed SAUR publication from a polling/API failure: fresh polling can continue while the published consumption itself grows older.

---

## Troubleshooting

**Invalid credentials during setup**

- Verify the same email and password on the SAUR customer portal.

**Cannot connect**

- The SAUR API may be temporarily unavailable.
- Check the Home Assistant logs and retry later.

**Estimated water index does not advance**

- Check the latest daily consumption date: SAUR may not have published newer daily data yet.
- If a required monthly request returns a temporary server error, SAURon keeps the last valid estimate and retries automatically.
- The physical `Water index` and the normal daily/weekly/monthly/yearly sensors remain independent from the reconstructed index.

**Stale data Repair Issue**

- Compare **Data age** with **Last successful poll**. A recent successful poll with an old daily-consumption date normally means SAUR has not published new consumption yet.
- Check whether new consumption is visible on the SAUR portal.
- The stale-data threshold can be changed from the integration options.

---

## Technical notes

- The integration uses Home Assistant's bundled `aiohttp`; no external Python library is required.
- The estimated cumulative index is reconstructed exclusively from daily `Day` entries returned by the monthly consumption endpoint.
- Entries are included only when their date is strictly later than the latest physical reading date.
- Malformed values outside the reconstruction date range are ignored; malformed required in-range data prevents publishing a newly calculated estimate.
- HTTP 5xx responses from SAUR data endpoints are treated as transient server failures; HTTP 4xx handling remains separate.
- A new physical reading automatically rebases the reconstruction.
- Credentials remain stored in the Home Assistant config entry and are not sent to third parties by this integration.

---

## Development

Development and pull-request guidelines are documented in [`CONTRIBUTING.md`](CONTRIBUTING.md).

The project includes a `Makefile` so the Python quality checks can be run locally with the same entry point used by GitHub Actions:

```bash
python -m pip install --upgrade pip
python -m pip install -e . pytest pytest-asyncio pytest-cov ruff
make check
```

Useful individual targets include `make fix` (Ruff formatting and safe automatic lint fixes), `make format`, `make format-check`, `make lint`, `make test`, and `make clean`. Hassfest and HACS validation continue to run in GitHub Actions.

---

## Credits

SAURon was originally created by **Nicolas Diguet (@netnic0)**.

The estimated cumulative water index, updated dashboard, documentation and related development for v0.5.0 were contributed by **Nicolas Chantrein (@minimicro34)**.

---

## License

[GPL-3.0](LICENSE) — © 2026 Nicolas Diguet and Nicolas Chantrein.

This fork is distributed under GPL-3.0. It incorporates code originally
licensed under MIT by Nicolas Diguet (@netnic0); the original MIT license
and copyright notices are preserved in [LICENSE-MIT](LICENSE-MIT).

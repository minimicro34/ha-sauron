# SAURon — Home Assistant integration for SAUR water consumption

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![GitHub release](https://img.shields.io/github/v/release/netnic0/ha-sauron)](https://github.com/netnic0/ha-sauron/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Monitor your [SAUR](https://www.saur.fr) water consumption directly in Home Assistant — daily, weekly, monthly and yearly usage, with Energy Dashboard integration.

> **Status**: Beta — works in production, field-tested with a single meter installation.
> DE/ES translations were machine-authored and welcome native-speaker corrections.

---

## Features

- **8 sensor entities** per meter subscription:

| Entity | Unit | Description |
|---|---|---|
| Water index | m³ | Latest physical meter reading reported by SAUR |
| Estimated water index | m³ | Physical reading + daily consumption since that reading; recommended for Energy Dashboard → Water |
| Last reading date | date | Date of the latest physical SAUR reading |
| Daily consumption | L | Yesterday's usage |
| Weekly consumption | m³ | Current week total |
| Monthly consumption | m³ | Current month total |
| Yearly consumption | m³ | Current year total |
| Data age *(diagnostic)* | h | Hours since last API poll |

- **Energy Dashboard** compatible — add `Estimated water index` to **Settings → Energy → Water**
- **Automatic rebasing** — when SAUR publishes a new physical meter reading, the estimated index uses it as the new baseline and only accumulates consumption after that date
- **Re-authentication flow** — seamless credential update without removing the integration
- **Repair Issues** — HA alerts when data becomes stale (configurable threshold)
- **Options flow** — configure polling interval and stale-data threshold at runtime
- **Multi-account** — add multiple config entries for multiple subscriptions
- **Localised** — English, French, German, Spanish

---

## Requirements

- Home Assistant **2024.12.0** or later
- A [SAUR customer portal](https://mon-espace.saurclient.fr) account (email + password)
- Your meter must be enrolled in SAUR's remote-reading programme (most French meters since 2022)

---

## Installation

### Via HACS (recommended)

1. Open HACS in Home Assistant
2. Click **⋮ → Custom repositories**
3. Add `https://github.com/netnic0/ha-sauron` with category **Integration**
4. Search for **SAURon** and click **Download**
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/sauron/` folder to your `config/custom_components/` directory
2. Restart Home Assistant

---

## Configuration

1. Go to **Settings → Integrations → + Add Integration**
2. Search for **SAURon**
3. Enter your SAUR portal credentials (same as [mon-espace.saurclient.fr](https://mon-espace.saurclient.fr))
4. The integration auto-discovers your subscription ID — no manual entry needed

### Options

After setup, click **Configure** on the integration card to adjust:

| Option | Default | Description |
|---|---|---|
| Polling interval | 4 h | How often to query the SAUR API |
| Stale data threshold | 36 h | Hours before a Repair Issue is raised |

> SAUR updates consumption data once per day (J−1). Polling more often than every 4 hours is rarely useful.

---

## Energy Dashboard

Add the **Estimated water index** sensor to the HA Energy Dashboard:

1. Go to **Settings → Energy**
2. Under **Water**, click **Add water source**
3. Select `sensor.saur_water_meter_estimated_water_index`
4. Save

The estimated index starts from SAUR's latest physical meter reading and adds the daily consumption entries published after that reading date. When a technician visit produces a newer physical reading, that reading automatically becomes the new baseline; consumption on and before the new reading date is no longer part of the estimate.

The original **Water index** sensor remains available unchanged and always exposes the latest physical reading returned by SAUR.

### utility_meter (optional)

For daily/weekly/monthly resets independent of the SAUR API:

```yaml
# configuration.yaml
utility_meter:
  water_daily:
    source: sensor.saur_water_meter_estimated_water_index
    cycle: daily
  water_monthly:
    source: sensor.saur_water_meter_estimated_water_index
    cycle: monthly
```

---

## Data freshness

SAUR publishes consumption data once per day, typically for J−1.
The `Daily consumption` sensor will show **Unknown** until a daily value is available.
The physical `Water index` may be updated much less frequently than daily consumption; this is why the integration exposes the separate cumulative `Estimated water index` sensor.

---

## Troubleshooting

**"Invalid credentials" during setup**
- Double-check your email and password on [mon-espace.saurclient.fr](https://mon-espace.saurclient.fr)
- SAUR accounts with two-factor authentication are not yet supported

**"Cannot connect"**
- The SAUR API (`apib2c.azure.saurclient.fr`) may be temporarily unavailable
- Check your internet connection and retry

**Sensors show "Unknown" after install**
- SAUR consumption data updates once per day — wait up to 24 hours for the first readings
- Check the HA logs for debug output: enable `custom_components.sauron: debug` in your `logger:` config

**Estimated water index shows "Unknown"**
- SAURon could not retrieve or validate one of the monthly consumption payloads required since the last physical reading
- The physical `Water index` and the other consumption sensors remain independent of this reconstruction

**Stale data alert in Repairs**
- Your meter may not be transmitting (check the SAUR portal)
- The threshold is configurable via **Configure** on the integration card

---

## Technical notes

- The SAUR mobile API accepts `captchaToken: "true"` as a literal string — no browser automation or real reCAPTCHA solving is required
- The estimated cumulative index is reconstructed from monthly API responses containing daily `Day` entries; the day of the physical reading itself is excluded to avoid double counting
- No external Python library dependency — uses HA's bundled `aiohttp`
- All credentials are stored in HA's config entry and never sent to third parties

---

## License

[MIT](LICENSE) — © 2026 Nicolas Diguet

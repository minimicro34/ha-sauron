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

💧 Daily usage • 📅 Weekly / monthly / yearly totals • 🔢 Estimated cumulative index • 📈 Energy Dashboard

---

SAURon is a custom Home Assistant integration for customers of the **SAUR** water service.

It retrieves the consumption data exposed by the SAUR customer API and provides native Home Assistant sensors. Because SAUR's physical meter index may only be refreshed when an official reading is performed, SAURon also reconstructs an estimated cumulative index from the latest physical reading and the daily consumption data published afterwards.

## Features

- **8 sensor entities** per meter subscription:

| Entity | Unit | Description |
|---|---|---|
| Water index | m³ | Latest physical meter reading reported by SAUR |
| Estimated water index | m³ | Physical reading + daily consumption since that reading; recommended for Energy Dashboard → Water |
| Last reading date | date | Date of the latest physical SAUR reading |
| Daily consumption | L | Latest daily consumption (normally J−1) |
| Weekly consumption | m³ | Current week total reported by SAUR |
| Monthly consumption | m³ | Current month total reported by SAUR |
| Yearly consumption | m³ | Current year total reported by SAUR |
| Data age *(diagnostic)* | h | Hours since the latest successful API poll |

- **Energy Dashboard compatible** — use `Estimated water index` as the water source.
- **Automatic rebasing** — when SAUR publishes a new physical meter reading, it becomes the new baseline automatically.
- **Historical reconstruction** — daily entries from each required month are accumulated after the physical reading date.
- **Safe reconstruction** — if a required historical monthly payload cannot be retrieved or validated, the estimated index is unavailable instead of publishing an incomplete cumulative value.
- **Re-authentication flow** — credentials can be updated without removing the integration.
- **Repair Issues** — Home Assistant warns when data becomes stale.
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
| Stale data threshold | 36 h | Age at which Home Assistant raises a Repair Issue |

SAUR normally publishes consumption data once per day, so a short polling interval is generally unnecessary.

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

---

## Energy Dashboard

Use the **Estimated water index** sensor for Home Assistant's water statistics:

1. Go to **Settings → Energy**.
2. Under **Water**, select **Add water source**.
3. Select the `Estimated water index` entity created by SAURon.
4. Save.

The sensor uses `device_class: water` and `state_class: total_increasing` and is expressed in m³.

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

## Lovelace dashboard example

A complete example is available in [`lovelace_examples/water_dashboard.yaml`](lovelace_examples/water_dashboard.yaml).

It includes:

- J−1, current week, month and year consumption;
- 7-day and 30-day consumption graphs based on the estimated cumulative index;
- the estimated and physical meter indexes;
- optional `utility_meter` daily and monthly counters;
- data freshness diagnostics;
- physical meter metadata such as serial number, manufacturer, model, diameter and remote-reading technology.

The example uses Mushroom, ApexCharts Card and card-mod.

---

## Data freshness

SAUR publishes consumption data once per day, typically for J−1. The physical meter index can remain unchanged for much longer because it corresponds to an official meter reading rather than the daily consumption feed.

The `Daily consumption` sensor may therefore remain unchanged until a new daily value is published. This does not prevent the week, month and year totals from reflecting the data available from SAUR.

---

## Troubleshooting

**Invalid credentials during setup**

- Verify the same email and password on the SAUR customer portal.

**Cannot connect**

- The SAUR API may be temporarily unavailable.
- Check the Home Assistant logs and retry later.

**Estimated water index is unavailable**

- SAURon could not retrieve or validate one of the monthly payloads needed between the physical reading and the latest consumption date.
- The physical `Water index` and the normal daily/weekly/monthly/yearly sensors remain independent from the reconstructed index.

**Stale data Repair Issue**

- Check whether new consumption is visible on the SAUR portal.
- The stale-data threshold can be changed from the integration options.

---

## Technical notes

- The integration uses Home Assistant's bundled `aiohttp`; no external Python library is required.
- The estimated cumulative index is reconstructed exclusively from daily `Day` entries returned by the monthly consumption endpoint.
- Entries are included only when their date is strictly later than the latest physical reading date.
- A new physical reading automatically rebases the reconstruction.
- Credentials remain stored in the Home Assistant config entry and are not sent to third parties by this integration.

---

## Credits

SAURon was originally created by **Nicolas Diguet (@netnic0)**.

The estimated cumulative water index, updated dashboard, documentation and related development for v0.5.0 were contributed by **Nicolas Chantrein (@minimicro34)**.

---

## License

[MIT](LICENSE) — © 2026 Nicolas Diguet and Nicolas Chantrein

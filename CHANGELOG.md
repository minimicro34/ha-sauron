# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.2](https://github.com/minimicro34/ha-sauron/compare/v0.5.1...v0.5.2) - 2026-09-14

### Added

- Added a **Last successful poll** diagnostic timestamp so API health can be distinguished from delayed SAUR publication.
- Added data-freshness tests covering daily-date age calculation and the new default stale threshold.

### Changed

- **Data age** now measures the age of the latest daily consumption actually published by SAUR instead of the time elapsed since the latest API fetch.
- The stale-data Repair Issue now uses that same latest daily consumption date, keeping the diagnostic sensor and alert semantics aligned.
- The default stale-data threshold is now **72 hours** instead of 36 hours to better tolerate delayed publication across weekends; existing user-configured thresholds are preserved.
- The latest known daily consumption and its date are kept when a temporary monthly-data failure prevents fresh enrichment.
- Updated English, French, German and Spanish wording to distinguish data publication age from polling health.
- Bumped the integration manifest version to **0.5.2**.

## [0.5.1](https://github.com/minimicro34/ha-sauron/compare/v0.5.0...v0.5.1) - 2026-09-14

### Added

- Added a **Latest daily consumption date** diagnostic sensor so delayed SAUR daily values are no longer presented without their actual date.
- Added retry backoff for temporary server-side failures affecting estimated-index reconstruction: 2 minutes, then 5 minutes, then 10 minutes until recovery.
- Added recovery logging when historical monthly data becomes available again.
- Added tests for delayed/unsorted daily values, retry backoff, last-value preservation and recovery.
- Added a `Makefile` for repeatable local compilation, formatting, linting and test commands.
- Added `CONTRIBUTING.md` with the local development, testing, translation and pull-request workflow.

### Changed

- Renamed the daily consumption label from "Yesterday consumption" / "Consommation J-1" to **Latest daily consumption** / **Dernière consommation journalière**.
- HTTP 5xx responses from SAUR data endpoints are now treated as transient server errors; HTTP 4xx handling remains separate.
- The estimated water index now keeps the last valid value during temporary historical-month failures instead of becoming unavailable.
- Estimated-index parsing now ignores malformed values outside the required reconstruction date range while still rejecting malformed in-range data.
- Updated English, French, German and Spanish translations and documentation to reflect delayed SAUR publication.
- Python quality validation now uses the same `make check` entry point locally and in GitHub Actions.

## [0.5.0](https://github.com/netnic0/ha-sauron/compare/ha-sauron-v0.4.1...minimicro34:v0.5.0) - 2026-09-12

### Added

- Added an **Estimated water index** sensor suitable for Home Assistant's Energy Dashboard.
- Reconstruct the cumulative water index from the latest physical SAUR reading plus daily consumption entries published after that reading date.
- Automatically rebase the estimated index whenever SAUR publishes a newer physical meter reading.
- Retrieve the historical monthly consumption payloads required to reconstruct consumption across month boundaries.
- Added tests for cumulative reconstruction, physical-reading rebasing, date boundaries, invalid payloads and rounding.
- Added English, French, German and Spanish translations for the estimated index sensor.
- Added an updated Lovelace water dashboard example with 7-day and 30-day graphs based on the estimated cumulative index.
- Added dashboard sections for optional `utility_meter` counters, diagnostics and physical meter metadata.

### Changed

- The original **Water index** sensor now remains explicitly documented as the latest physical meter reading reported by SAUR.
- Energy Dashboard documentation now recommends the **Estimated water index** instead of the physical reading.
- Refreshed the README and dashboard documentation for the reconstructed cumulative-index workflow.
- Simplified CI validation and aligned it with current project conventions.
- Releases are now managed manually by the maintainers.

### Removed

- Removed Release Please workflow and configuration files.

## [0.4.1](https://github.com/netnic0/ha-sauron/compare/ha-sauron-v0.4.0...ha-sauron-v0.4.1) (2026-06-17)

### Bug Fixes

* **entity,lovelace:** expose meter attrs + fix ApexCharts fill ([#23](https://github.com/netnic0/ha-sauron/issues/23)) ([5e95f51](https://github.com/netnic0/ha-sauron/commit/5e95f51edeb26b70c42a04248688f976525029ff))

## [0.4.0](https://github.com/netnic0/ha-sauron/compare/ha-sauron-v0.3.0...ha-sauron-v0.4.0) (2026-06-17)

### Features

* **device:** enrich device info + water dashboard improvements ([2462bbd](https://github.com/netnic0/ha-sauron/commit/2462bbde21232394ed0cd2393d10e26930fe7fd6))
* **device:** enrich DeviceInfo with meter hardware metadata from delivery_points ([502c5d9](https://github.com/netnic0/ha-sauron/commit/502c5d94c6ac1002a16295bf9d6296ab48e0145a))
* **lovelace:** add meter hardware info section to water dashboard ([46aac6a](https://github.com/netnic0/ha-sauron/commit/46aac6a35d5eba5ee2e8bd6e69fe7fd6))

## [0.3.0](https://github.com/netnic0/ha-sauron/compare/ha-sauron-v0.2.7...ha-sauron-v0.3.0) (2026-06-17)

### Features

* **coordinator:** use monthly endpoint for daily/weekly/monthly sensors ([a1b1ce2](https://github.com/netnic0/ha-sauron/commit/a1b1ce2922bc7759a0474b95324f834ca93243cc))
* **lovelace:** add water consumption dashboard blueprint ([5048521](https://github.com/netnic0/ha-sauron/commit/5048521bb7660b18c8d04eb7c0bcb2591e9ca0b2))

## [0.2.7](https://github.com/netnic0/ha-sauron/compare/ha-sauron-v0.2.6...ha-sauron-v0.2.7) (2026-06-17)

### Bug Fixes

* **integration:** address P0/P1 code review findings ([#23](https://github.com/netnic0/ha-sauron/commit/88470d677d981a5d4686966b5d98e2b56565edcd))

## [0.2.6](https://github.com/netnic0/ha-sauron/compare/ha-sauron-v0.2.5...ha-sauron-v0.2.6) (2026-06-17)

### Bug Fixes

* **coordinator:** query J-2 for weekly data; take last non-zero day entry ([5debbe1](https://github.com/netnic0/ha-sauron/commit/5debbe1633c61c0306f56b7d60704bb774f20e34))
* **coordinator:** query J-2 for weekly data; take last non-zero day entry ([ce6a5dd](https://github.com/netnic0/ha-sauron/commit/ce6a5dd3219a3402a16295bf9d6296ab48e0145a))

## [0.2.5](https://github.com/netnic0/ha-sauron/compare/ha-sauron-v0.2.4...ha-sauron-v0.2.5) (2026-06-17)

### Bug Fixes

* **sensor:** use TOTAL state_class for daily_liters ([fa09344](https://github.com/netnic0/ha-sauron/commit/fa09344cb3528c0ccafbffb6529e9060cd2af01))
* **sensor:** use TOTAL state_class for daily_liters (device_class=WATER requires TOTAL or TOTAL_INCREASING) ([eb69be4](https://github.com/netnic0/ha-sauron/commit/eb69be40acd994eb48e0145a))

## [0.2.4](https://github.com/netnic0/ha-sauron/compare/ha-sauron-v0.2.3...ha-sauron-v0.2.4) (2026-06-16)

### Bug Fixes

* **coordinator:** add debug log for weekly API response (diagnostic) ([49f0ddd](https://github.com/netnic0/ha-sauron/commit/49f0ddd7fd7f8b5b06522f22dc70c8f7f974bbdd))

## [0.2.3](https://github.com/netnic0/ha-sauron/compare/ha-sauron-v0.2.2...ha-sauron-v0.2.3) (2026-06-16)

### Bug Fixes

* **brand:** generate proper PNG assets from SAUR SVG + add icon.svg with water drop ([a6e7e19](https://github.com/netnic0/ha-sauron/commit/a6e7e198d9832b92e326336315311a679484d074))
* **coordinator:** query J-1 for daily/weekly data (SAUR always lags by 1 day) ([969d501](https://github.com/netnic0/ha-sauron/commit/969d501203d6f5efc8cd25105645e04eba72592d))
* **i18n+coordinator:** J-1 query, rename weekly/daily sensors, correct sensor date types ([1c989ce](https://github.com/netnic0/ha-sauron/commit/1c989ce67a2651d8884a76c5c999d753c91f80d8))

## [0.2.2](https://github.com/netnic0/ha-sauron/compare/ha-sauron-v0.2.1...ha-sauron-v0.2.2) (2026-06-16)

### Documentation

* add MIT license, expand README, fix sensor regression ([6e298ce](https://github.com/netnic0/ha-sauron/commit/6e298ce3eaf90af3c2a16295bf9d6296ab48e0145a))
* MIT license + expanded README + sensor date fix ([907d3e0](https://github.com/netnic0/ha-sauron/commit/907d3e01d3a9a595e67ac6a5a358aee53f3a024a))

## [0.2.1](https://github.com/netnic0/ha-sauron/compare/ha-sauron-v0.2.0...ha-sauron-v0.2.1) (2026-06-16)

### Bug Fixes

* **integration:** address P0/P1 code review findings ([d7756fd](https://github.com/netnic0/ha-sauron/commit/d7756fdeddbfc2ea83ceece8d445f6d8f00e5a07))
* **integration:** address P0/P1 code review findings ([034b6fe](https://github.com/netnic0/ha-sauron/commit/034b6feef15aad068a8e5eae4f3c72408840a741))

## [0.2.0](https://github.com/netnic0/ha-sauron/compare/ha-sauron-v0.1.0...ha-sauron-v0.2.0) (2026-06-16)

### Features

* **scaffold:** initial SAURon integration skeleton ([c354e1f](https://github.com/netnic0/ha-sauron/commit/c354e1f1f52218609a63a8cd2e2a6f986f5db143))

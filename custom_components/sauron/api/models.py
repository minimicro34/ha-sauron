"""Immutable data models for SAUR API responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class MeterInfo:
    """Static metadata for a water meter / subscription."""

    subscription_id: str
    """SAUR section_subscription identifier."""

    address: str
    """Delivery point address (human-readable)."""

    meter_serial: str
    """Physical meter serial number (serialNumber field from API)."""

    installation_date: date | None
    """Date the meter was installed, or None if unknown."""

    meter_brand: str = ""
    """Meter hardware manufacturer (meterBrandCode, e.g. 'ELSTER (MID)')."""

    meter_model: str = ""
    """Meter model (meterModelCode, e.g. 'tModele 156')."""

    meter_diameter: str = ""
    """Meter pipe diameter (meterDiameterCode, e.g. '15mm')."""

    telereleve_tech: str = ""
    """Remote reading technology (pairingTechnologyCode, e.g. 'TeleCoronis')."""


@dataclass(frozen=True, slots=True)
class MeterReading:
    """Latest known index reading for a meter."""

    subscription_id: str
    value_m3: float
    """Absolute index in cubic metres."""

    reading_date: date
    """Date the reading was taken (typically J-1)."""

    fetched_at: datetime
    """Timestamp when this reading was retrieved from the API."""


@dataclass(frozen=True, slots=True)
class ConsumptionPeriod:
    """Aggregated consumption for a given period."""

    subscription_id: str
    period_label: str
    """Human-readable label: e.g. '2026-06', '2026-W24', '2026'."""

    volume_m3: float
    """Water consumed during this period, in cubic metres."""

    start_date: date
    end_date: date


@dataclass(frozen=True, slots=True)
class SauronData:
    """Full coordinator snapshot: one entry per subscription."""

    meter_info: MeterInfo
    latest_reading: MeterReading
    estimated_index_m3: float | None = None
    """Estimated cumulative index based on the last physical reading plus daily usage."""

    daily_liters: float | None = None
    """Most recent daily consumption published by SAUR, in litres."""

    daily_date: date | None = None
    """Date associated with the most recent daily consumption published by SAUR."""

    weekly_m3: float | None = None
    monthly_m3: float | None = None
    yearly_m3: float | None = None

    consumptions: tuple[ConsumptionPeriod, ...] = field(default_factory=tuple)

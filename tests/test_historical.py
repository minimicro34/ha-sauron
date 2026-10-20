"""Read-only historical backfill preparation tests."""

import sys
import types
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.sauron import (
    _async_preview_historical,
    _async_preview_historical_coverage,
)
from custom_components.sauron.const import DOMAIN
from custom_components.sauron.coordinator import SauronCoordinator
from custom_components.sauron.historical import (
    preview_monthly_payloads,
    summarize_historical_coverage,
)


def _payload(*items):
    return {
        "consumptions": [
            {"rangeType": "Day", "startDate": day, "value": value}
            for day, value in items
        ]
    }


def test_explicit_zero_is_not_missing():
    result = preview_monthly_payloads(
        [_payload(("2023-10-19", 0), ("2023-10-20", 0.1))],
        date(2023, 10, 19),
        date(2023, 10, 20),
    )
    assert result.complete
    assert result.values["2023-10-19"] == 0


def test_missing_dates_are_not_assumed_zero():
    result = preview_monthly_payloads(
        [_payload(("2023-10-20", 0.1))],
        date(2023, 10, 19),
        date(2023, 10, 21),
    )
    assert result.missing_days == ("2023-10-19", "2023-10-21")
    assert not result.complete


def test_existing_overlap_is_reported_without_mutation():
    existing = {"2026-05-29": 0.2}
    result = preview_monthly_payloads(
        [_payload(("2026-05-29", 0.3))],
        date(2026, 5, 29),
        date(2026, 5, 29),
        existing,
    )
    assert result.conflicts_with_ledger == {"2026-05-29": (0.2, 0.3)}
    assert existing == {"2026-05-29": 0.2}


def test_identical_duplicates_are_accepted():
    result = preview_monthly_payloads(
        [_payload(("2023-10-20", 0.1)), _payload(("2023-10-20", 0.1))],
        date(2023, 10, 20),
        date(2023, 10, 20),
    )
    assert result.complete


def test_conflicting_duplicates_are_rejected():
    with pytest.raises(ValueError, match="Conflicting historical"):
        preview_monthly_payloads(
            [_payload(("2023-10-20", 0.1)), _payload(("2023-10-20", 0.2))],
            date(2023, 10, 20),
            date(2023, 10, 20),
        )


@pytest.mark.parametrize("value", [-0.1, float("nan"), float("inf")])
def test_invalid_volume_is_rejected(value):
    with pytest.raises(ValueError, match="Invalid historical SAUR daily volume"):
        preview_monthly_payloads(
            [_payload(("2023-10-20", value))],
            date(2023, 10, 20),
            date(2023, 10, 20),
        )


def test_invalid_payload_is_rejected():
    with pytest.raises(ValueError, match="Invalid historical SAUR response"):
        preview_monthly_payloads(
            [{}], date(2023, 10, 20), date(2023, 10, 20)
        )


def test_available_ranges_keep_missing_days_as_gaps():
    result = preview_monthly_payloads(
        [_payload(
            ("2023-10-20", 0.1),
            ("2023-10-21", 0),
            ("2023-10-23", 0.2),
        )],
        date(2023, 10, 20),
        date(2023, 10, 24),
    )
    assert result.available_ranges == (
        ("2023-10-20", "2023-10-21"),
        ("2023-10-23", "2023-10-23"),
    )
    assert result.missing_days == ("2023-10-22", "2023-10-24")


def test_available_ranges_empty_when_no_readings():
    result = preview_monthly_payloads(
        [_payload()], date(2023, 10, 20), date(2023, 10, 21)
    )
    assert result.available_ranges == ()


def test_non_mapping_payload_is_rejected():
    with pytest.raises(ValueError, match="Invalid historical SAUR response"):
        preview_monthly_payloads(
            [None], date(2023, 10, 20), date(2023, 10, 20)
        )


@pytest.mark.asyncio
async def test_service_preview_read_only(monkeypatch, fake_entry):
    """Preview must report coverage and leave existing config data untouched."""
    errors = types.ModuleType("homeassistant.exceptions")
    class HomeAssistantError(Exception):
        pass
    errors.HomeAssistantError = HomeAssistantError
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", errors)

    fake_entry.data["subscription_id"] = "SUB001"
    client = AsyncMock()
    client.async_get_monthly.return_value = _payload(
        ("2023-10-20", 0.1), ("2023-10-21", 0)
    )
    coordinator = object.__new__(SauronCoordinator)
    coordinator.config_entry = fake_entry
    coordinator._client = client
    hass = SimpleNamespace(data={DOMAIN: {fake_entry.entry_id: coordinator}})
    before = dict(fake_entry.data)
    result = await _async_preview_historical(
        hass,
        SimpleNamespace(data={
            "entry_id": fake_entry.entry_id,
            "start": "2023-10-20",
            "end": "2023-10-22",
        }),
    )
    assert result["read_only"] is True
    assert result["returned_days"] == 2
    assert result["missing_days"] == ["2023-10-22"]
    assert result["available_ranges"] == [["2023-10-20", "2023-10-21"]]
    assert fake_entry.data == before
    client.async_get_monthly.assert_awaited_once_with("SUB001", 2023, 10)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("bad-date", "2023-10-21"),
        ("2023-10-22", "2023-10-20"),
        ("2023-10-01", "2023-11-07"),
    ],
)
async def test_service_rejects_invalid_dates(monkeypatch, fake_entry, start, end):

    errors = types.ModuleType("homeassistant.exceptions")
    class HomeAssistantError(Exception):
        pass
    errors.HomeAssistantError = HomeAssistantError
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", errors)
    coordinator = object.__new__(SauronCoordinator)
    coordinator.config_entry = fake_entry
    coordinator._client = AsyncMock()
    hass = SimpleNamespace(data={DOMAIN: {fake_entry.entry_id: coordinator}})
    with pytest.raises(HomeAssistantError):
        await _async_preview_historical(
            hass,
            SimpleNamespace(data={
                "entry_id": fake_entry.entry_id,
                "start": start,
                "end": end,
            }),
        )
    coordinator._client.async_get_monthly.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_rejects_unknown_entry(monkeypatch):
    import sys
    import types

    errors = types.ModuleType("homeassistant.exceptions")
    class HomeAssistantError(Exception):
        pass
    errors.HomeAssistantError = HomeAssistantError
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", errors)
    with pytest.raises(HomeAssistantError, match="Unknown"):
        await _async_preview_historical(
            SimpleNamespace(data={DOMAIN: {}}),
            SimpleNamespace(data={
                "entry_id": "unknown",
                "start": "2023-10-20",
                "end": "2023-10-21",
            }),
        )


def test_coverage_monthly_summary_and_ledger_overlap():
    ledger = {"2023-10-31": 0.1, "2023-11-01": 0.2}
    preview = preview_monthly_payloads(
        [_payload(("2023-10-31", 0.1), ("2023-11-01", 0.3))],
        date(2023, 10, 30),
        date(2023, 11, 2),
        ledger,
    )
    result = summarize_historical_coverage(preview, ledger)
    assert result["expected_days"] == 4
    assert result["returned_days"] == 2
    assert result["missing_days"] == ["2023-10-30", "2023-11-02"]
    assert result["ledger_overlap_days"] == 2
    assert result["ledger_conflicts"]["2023-11-01"] == {
        "existing": 0.2, "received": 0.3
    }
    assert result["months"] == [
        {
            "month": "2023-10", "expected_days": 2, "returned_days": 1,
            "missing_days": 1, "ledger_overlap_days": 1, "ledger_conflicts": 0,
        },
        {
            "month": "2023-11", "expected_days": 2, "returned_days": 1,
            "missing_days": 1, "ledger_overlap_days": 1, "ledger_conflicts": 1,
        },
    ]
    assert result["recorder_verified"] is False
    assert result["read_only"] is True
    assert ledger == {"2023-10-31": 0.1, "2023-11-01": 0.2}


@pytest.mark.asyncio
async def test_coverage_action_fetches_two_months_without_mutation(monkeypatch, fake_entry):
    errors = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    errors.HomeAssistantError = HomeAssistantError
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", errors)
    client = AsyncMock()
    client.async_get_monthly.side_effect = [
        _payload(("2023-10-31", 0.1)),
        _payload(("2023-11-01", 0.2)),
    ]
    coordinator = object.__new__(SauronCoordinator)
    coordinator.config_entry = fake_entry
    coordinator._client = client
    hass = SimpleNamespace(data={DOMAIN: {fake_entry.entry_id: coordinator}})
    before = dict(fake_entry.data)
    result = await _async_preview_historical_coverage(
        hass,
        SimpleNamespace(data={
            "entry_id": fake_entry.entry_id,
            "start": "2023-10-31",
            "end": "2023-11-01",
        }),
    )
    assert result["complete"] is True
    assert result["returned_days"] == 2
    assert result["recorder_verified"] is False
    assert fake_entry.data == before
    assert client.async_get_monthly.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2023-10-01", "2026-10-01"),
        ("2024-01-02", "2024-01-01"),
        ("not-a-date", "2024-01-01"),
    ],
)
async def test_coverage_action_rejects_invalid_range(monkeypatch, fake_entry, start, end):
    errors = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    errors.HomeAssistantError = HomeAssistantError
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", errors)
    coordinator = object.__new__(SauronCoordinator)
    coordinator.config_entry = fake_entry
    coordinator._client = AsyncMock()
    hass = SimpleNamespace(data={DOMAIN: {fake_entry.entry_id: coordinator}})
    with pytest.raises(HomeAssistantError):
        await _async_preview_historical_coverage(
            hass,
            SimpleNamespace(data={
                "entry_id": fake_entry.entry_id,
                "start": start,
                "end": end,
            }),
        )
    coordinator._client.async_get_monthly.assert_not_awaited()


def test_backfill_plan_preserves_existing_recorder_sums():
    from custom_components.sauron.historical import plan_historical_backfill
    from custom_components.sauron.statistics import build_ledger_statistics

    history = preview_monthly_payloads(
        [_payload(("2026-05-27", 0.4), ("2026-05-28", 0.6))],
        date(2026, 5, 27),
        date(2026, 5, 28),
    )
    ledger = {"2026-05-29": 0.2, "2026-05-30": 0.3}
    existing = build_ledger_statistics(ledger, "Europe/Paris")
    result = plan_historical_backfill(history, ledger, existing, "Europe/Paris")
    assert result["recorder_verified"] is True
    assert result["historical_days"] == 2
    assert result["existing_rows_unchanged"] is True
    assert [row["sum"] for row in result["historical_rows"]] == [-0.6, 0.0]
    assert existing == build_ledger_statistics(ledger, "Europe/Paris")


@pytest.mark.parametrize("tamper", ["missing", "sum", "state", "timestamp"])
def test_backfill_plan_rejects_recorder_discrepancies(tamper):
    from datetime import timedelta

    from custom_components.sauron.historical import plan_historical_backfill
    from custom_components.sauron.statistics import build_ledger_statistics

    history = preview_monthly_payloads(
        [_payload(("2026-05-28", 0.4))],
        date(2026, 5, 28),
        date(2026, 5, 28),
    )
    ledger = {"2026-05-29": 0.2}
    rows = build_ledger_statistics(ledger, "Europe/Paris")
    if tamper == "missing":
        rows = []
    elif tamper == "timestamp":
        rows[0]["start"] += timedelta(hours=1)
    else:
        rows[0][tamper] += 0.1
    with pytest.raises(ValueError, match="Recorder"):
        plan_historical_backfill(history, ledger, rows, "Europe/Paris")


def test_backfill_plan_rejects_missing_historical_boundary():
    from custom_components.sauron.historical import plan_historical_backfill
    from custom_components.sauron.statistics import build_ledger_statistics

    history = preview_monthly_payloads(
        [_payload(("2026-05-27", 0.4))],
        date(2026, 5, 27),
        date(2026, 5, 27),
    )
    ledger = {"2026-05-29": 0.2}
    with pytest.raises(ValueError, match="exactly one day"):
        plan_historical_backfill(
            history, ledger, build_ledger_statistics(ledger, "UTC"), "UTC"
        )


@pytest.mark.asyncio
async def test_import_rejects_missing_confirmation(monkeypatch, fake_entry):
    """An unconfirmed action must never fetch or enqueue Recorder writes."""
    from custom_components.sauron import _async_import_historical

    errors = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    errors.HomeAssistantError = HomeAssistantError
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", errors)
    coordinator = object.__new__(SauronCoordinator)
    coordinator.config_entry = fake_entry
    coordinator._client = AsyncMock()
    hass = SimpleNamespace(data={DOMAIN: {fake_entry.entry_id: coordinator}})
    with pytest.raises(HomeAssistantError, match="confirm"):
        await _async_import_historical(
            hass,
            SimpleNamespace(data={
                "entry_id": fake_entry.entry_id,
                "start": "2023-10-16",
                "end": "2026-05-28",
                "confirm": False,
            }),
        )
    coordinator._client.async_get_monthly.assert_not_awaited()


def test_backfill_plan_rejects_existing_history_and_ledger_gaps():
    from custom_components.sauron.historical import plan_historical_backfill

    history = preview_monthly_payloads(
        [_payload(("2026-05-28", 0.4))],
        date(2026, 5, 28),
        date(2026, 5, 28),
    )
    ledger = {"2026-05-29": 0.2, "2026-05-31": 0.3}
    with pytest.raises(ValueError, match="missing days"):
        plan_historical_backfill(history, ledger, [], "UTC")


def test_backfill_plan_rejects_incomplete_history():
    from custom_components.sauron.historical import plan_historical_backfill
    from custom_components.sauron.statistics import build_ledger_statistics

    history = preview_monthly_payloads(
        [_payload(("2026-05-27", 0.4))],
        date(2026, 5, 27),
        date(2026, 5, 28),
    )
    ledger = {"2026-05-29": 0.2}
    with pytest.raises(ValueError, match="Incomplete historical"):
        plan_historical_backfill(
            history, ledger, build_ledger_statistics(ledger, "UTC"), "UTC"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("tamper", [False, True])
async def test_manual_import_queues_only_after_recorder_preflight(
    monkeypatch, fake_entry, tamper
):
    from unittest.mock import Mock

    from custom_components.sauron import _async_import_historical
    from custom_components.sauron.statistics import build_ledger_statistics

    errors = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    errors.HomeAssistantError = HomeAssistantError
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", errors)

    recorder_models = types.ModuleType("homeassistant.components.recorder.models.statistics")
    recorder_models.StatisticMeanType = SimpleNamespace(NONE="none")
    monkeypatch.setitem(
        sys.modules, "homeassistant.components.recorder.models.statistics", recorder_models
    )
    recorder_stats = types.ModuleType("homeassistant.components.recorder.statistics")
    recorder_stats.async_add_external_statistics = Mock()
    recorder_stats.statistics_during_period = Mock()
    monkeypatch.setitem(
        sys.modules, "homeassistant.components.recorder.statistics", recorder_stats
    )

    fake_entry.data["subscription_id"] = "SUB001"
    fake_entry.data["_dated_statistics_daily_ledger"] = {"2026-05-29": 0.2}
    client = AsyncMock()
    client.async_get_monthly.return_value = _payload(("2026-05-28", 0.4))
    coordinator = object.__new__(SauronCoordinator)
    coordinator.config_entry = fake_entry
    coordinator._client = client
    rows = build_ledger_statistics({"2026-05-29": 0.2}, "Europe/Paris")
    recorded = [
        {"start": row["start"].timestamp(), "state": row["state"], "sum": row["sum"]}
        for row in rows
    ]
    if tamper:
        recorded[0]["sum"] = 0.5

    async def executor_job(func):
        return func()

    recorder_module = types.ModuleType("homeassistant.components.recorder")
    recorder_module.get_instance = lambda _hass: SimpleNamespace(
        async_add_executor_job=executor_job
    )
    monkeypatch.setitem(
        sys.modules, "homeassistant.components.recorder", recorder_module
    )
    recorder_stats.statistics_during_period.return_value = {
        f"sauron:daily_water_{fake_entry.entry_id.lower()}": recorded
    }
    update_entry = Mock()
    hass = SimpleNamespace(
        data={DOMAIN: {fake_entry.entry_id: coordinator}},
        config=SimpleNamespace(time_zone="Europe/Paris"),
        config_entries=SimpleNamespace(async_update_entry=update_entry),
        async_add_executor_job=executor_job,
    )
    call = SimpleNamespace(data={
        "entry_id": fake_entry.entry_id,
        "start": "2026-05-28",
        "end": "2026-05-28",
        "confirm": True,
    })
    if tamper:
        with pytest.raises(HomeAssistantError, match="Recorder sum"):
            await _async_import_historical(hass, call)
        recorder_stats.async_add_external_statistics.assert_not_called()
        update_entry.assert_not_called()
    else:
        result = await _async_import_historical(hass, call)
        assert result["status"] == "queued"
        assert result["recorder_write_completed"] is False
        assert result["historical_days"] == 1
        recorder_stats.async_add_external_statistics.assert_called_once()
        update_entry.assert_called_once()
        backup = update_entry.call_args.kwargs["data"]["_historical_import_backup"]
        assert backup["recorder_rows"][0]["sum"] == 0.2
        assert backup["historical_total_m3"] == 0.4


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("unknown_entry", "Unknown SAURon"),
        ("no_ledger", "Missing persisted"),
        ("bad_date", "Invalid isoformat"),
        ("reversed_dates", "at most 36"),
        ("too_many_months", "at most 36"),
        ("wrong_boundary", "join the existing"),
        ("no_recorder", "no existing"),
        ("already_imported", "already contains historical"),
        ("ledger_changed", "ledger changed"),
        ("already_queued", "Previous historical import"),
    ],
)
async def test_import_fail_closed_paths(monkeypatch, fake_entry, case, expected):
    from unittest.mock import Mock

    from custom_components.sauron import _async_import_historical
    from custom_components.sauron.statistics import build_ledger_statistics

    errors = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    errors.HomeAssistantError = HomeAssistantError
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", errors)
    models = types.ModuleType("homeassistant.components.recorder.models.statistics")
    models.StatisticMeanType = SimpleNamespace(NONE="none")
    monkeypatch.setitem(
        sys.modules, "homeassistant.components.recorder.models.statistics", models
    )
    stats = types.ModuleType("homeassistant.components.recorder.statistics")
    stats.async_add_external_statistics = Mock()
    stats.statistics_during_period = Mock()
    monkeypatch.setitem(
        sys.modules, "homeassistant.components.recorder.statistics", stats
    )
    fake_entry.data["subscription_id"] = "SUB001"
    ledger = {"2026-05-29": 0.2}
    fake_entry.data["_dated_statistics_daily_ledger"] = ledger
    coordinator = object.__new__(SauronCoordinator)
    coordinator.config_entry = fake_entry
    coordinator._client = AsyncMock()
    coordinator._client.async_get_monthly.return_value = _payload(
        ("2026-05-28", 0.4)
    )
    statistic_id = f"sauron:daily_water_{fake_entry.entry_id.lower()}"
    recorded = [
        {"start": row["start"].timestamp(), "state": row["state"], "sum": row["sum"]}
        for row in build_ledger_statistics(ledger, "Europe/Paris")
    ]
    if case == "no_recorder":
        recorded = []
    if case == "already_imported":
        recorded.insert(
            0, {**recorded[0], "start": recorded[0]["start"] - 86400}
        )
    recorder_module = types.ModuleType("homeassistant.components.recorder")
    recorder_module.get_instance = lambda _hass: SimpleNamespace(
        async_add_executor_job=executor_job
    )
    monkeypatch.setitem(
        sys.modules, "homeassistant.components.recorder", recorder_module
    )
    stats.statistics_during_period.return_value = {statistic_id: recorded}
    update_entry = Mock()

    async def executor_job(func):
        return func()

    hass = SimpleNamespace(
        data={DOMAIN: {fake_entry.entry_id: coordinator}},
        config=SimpleNamespace(time_zone="Europe/Paris"),
        config_entries=SimpleNamespace(async_update_entry=update_entry),
        async_add_executor_job=executor_job,
    )
    call = {
        "entry_id": fake_entry.entry_id,
        "start": "2026-05-28",
        "end": "2026-05-28",
        "confirm": True,
    }
    if case == "unknown_entry":
        hass.data[DOMAIN] = {}
    elif case == "no_ledger":
        del fake_entry.data["_dated_statistics_daily_ledger"]
    elif case == "bad_date":
        call["start"] = "bad"
    elif case == "reversed_dates":
        call["start"] = "2026-05-29"
    elif case == "too_many_months":
        call["start"] = "2023-05-28"
    elif case == "wrong_boundary":
        call["start"] = "2026-05-27"
        call["end"] = "2026-05-27"
    elif case == "ledger_changed":
        original = coordinator._client.async_get_monthly

        async def change_ledger(*args):
            fake_entry.data["_dated_statistics_daily_ledger"] = {
                **ledger, "2026-05-30": 0.1
            }
            return await original(*args)

        coordinator._client.async_get_monthly = change_ledger
    elif case == "already_queued":
        fake_entry.data["_historical_import_backup"] = {"status": "queued"}

    with pytest.raises(HomeAssistantError, match=expected):
        await _async_import_historical(hass, SimpleNamespace(data=call))
    stats.async_add_external_statistics.assert_not_called()
    update_entry.assert_not_called()


def test_preview_rejects_reversed_dates():
    with pytest.raises(ValueError, match="start must not exceed"):
        preview_monthly_payloads([], date(2026, 5, 29), date(2026, 5, 28))


@pytest.mark.asyncio
async def test_fetch_rejects_reversed_dates_before_api_call():
    from custom_components.sauron.historical import fetch_historical_preview

    client = SimpleNamespace(async_get_monthly=AsyncMock())
    with pytest.raises(ValueError, match="start must not exceed"):
        await fetch_historical_preview(
            client, "subscription", date(2026, 5, 29), date(2026, 5, 28)
        )
    client.async_get_monthly.assert_not_awaited()


def test_preview_ignores_monthly_and_out_of_range_readings():
    payload = {
        "consumptions": [
            {"rangeType": "Month", "startDate": "2026-05-28", "value": 99},
            {"rangeType": "Day", "startDate": "2026-05-27", "value": 0.9},
            {"rangeType": "Day", "startDate": "2026-05-28", "value": 0.4},
            {"rangeType": "Day", "startDate": "2026-05-29", "value": 0.7},
        ]
    }
    result = preview_monthly_payloads(
        [payload], date(2026, 5, 28), date(2026, 5, 28)
    )
    assert result.values == {"2026-05-28": 0.4}


@pytest.mark.parametrize(
    "reading",
    [
        {"rangeType": "Day", "value": 0.4},
        {"rangeType": "Day", "startDate": "invalid", "value": 0.4},
        {"rangeType": "Day", "startDate": "2026-05-28", "value": None},
    ],
)
def test_preview_rejects_malformed_day(reading):
    with pytest.raises(ValueError, match="Invalid historical SAUR daily reading"):
        preview_monthly_payloads(
            [{"consumptions": [reading]}],
            date(2026, 5, 28),
            date(2026, 5, 28),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "case", "expected"),
    [
        ("preview", "api_error", "preview failed"),
        ("coverage", "api_error", "coverage failed"),
        ("coverage", "unknown", "Unknown SAURon"),
        ("coverage", "invalid_ledger", "Invalid persisted"),
    ],
)
async def test_read_only_services_fail_closed(
    monkeypatch, fake_entry, action, case, expected
):
    errors = types.ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        pass

    errors.HomeAssistantError = HomeAssistantError
    monkeypatch.setitem(sys.modules, "homeassistant.exceptions", errors)
    coordinator = object.__new__(SauronCoordinator)
    coordinator.config_entry = fake_entry
    coordinator._client = AsyncMock()
    coordinator._client.async_get_monthly.side_effect = RuntimeError("SAUR unavailable")
    hass = SimpleNamespace(data={DOMAIN: {fake_entry.entry_id: coordinator}})
    if case == "unknown":
        hass.data[DOMAIN] = {}
    if case == "invalid_ledger":
        fake_entry.data["_dated_statistics_daily_ledger"] = ["invalid"]
    service = (
        _async_preview_historical if action == "preview"
        else _async_preview_historical_coverage
    )
    with pytest.raises(HomeAssistantError, match=expected):
        await service(
            hass,
            SimpleNamespace(data={
                "entry_id": fake_entry.entry_id,
                "start": "2026-05-28",
                "end": "2026-05-28",
            }),
        )
    if case != "api_error":
        coordinator._client.async_get_monthly.assert_not_awaited()


def test_positive_baseline_repair_preserves_daily_consumption():
    from custom_components.sauron.historical import (
        plan_historical_backfill,
        plan_positive_baseline_repair,
    )
    from custom_components.sauron.statistics import build_ledger_statistics

    preview = preview_monthly_payloads(
        [_payload(("2026-05-27", 0.4), ("2026-05-28", 0.6))],
        date(2026, 5, 27), date(2026, 5, 28),
    )
    ledger = {"2026-05-29": 0.2, "2026-05-30": 0.3}
    existing = build_ledger_statistics(ledger, "Europe/Paris")
    plan = plan_historical_backfill(preview, ledger, existing, "Europe/Paris")
    historical = plan["historical_rows"]
    assert [row["sum"] for row in historical] == [-0.6, 0.0]
    repaired = plan_positive_baseline_repair(historical, existing)
    assert repaired["read_only"] is True
    assert repaired["recorder_write_completed"] is False
    assert repaired["offset_m3"] == 1.0
    assert [row["sum"] for row in repaired["historical_rows"]] == [0.4, 1.0]
    assert [row["sum"] for row in repaired["existing_rows"]] == [1.2, 1.5]
    assert [row["state"] for row in repaired["existing_rows"]] == [0.2, 0.3]
    assert [row["sum"] for row in existing] == [0.2, 0.5]


def test_positive_baseline_repair_rejects_inconsistent_series():
    from custom_components.sauron.historical import plan_positive_baseline_repair
    from custom_components.sauron.statistics import build_ledger_statistics

    historical = build_ledger_statistics({"2026-05-28": 0.4}, "UTC")
    existing = build_ledger_statistics({"2026-05-29": 0.2}, "UTC")
    with pytest.raises(ValueError, match="No negative historical baseline"):
        plan_positive_baseline_repair(historical, existing)

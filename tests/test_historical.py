"""Read-only historical backfill preparation tests."""

from datetime import date

import pytest

from custom_components.sauron.historical import preview_monthly_payloads


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

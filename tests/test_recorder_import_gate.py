"""Regression coverage for historical import and Recorder publication gating."""

import sys
from datetime import date
from unittest.mock import patch

from tests.test_recorder_publish import _coordinator, _recorder_modules


def test_pending_import_does_not_publish_or_change_ledger():
    coordinator, entry, hass = _coordinator(
        ledger={"2026-10-11": 0.9},
        payload=[{"consumptions": [
            {"rangeType": "Day", "startDate": "2026-10-12", "value": 0.2}
        ]}],
    )
    entry.data["_historical_import_backup"] = {"status": "queued_positive"}
    entry.data["_historical_baseline_repair"] = {
        "status": "pending", "offset_m3": 1.0,
    }
    modules = _recorder_modules()
    with patch.dict(sys.modules, modules):
        coordinator._publish_dated_statistics(date(2026, 10, 11), date(2026, 10, 12))
    writer = modules["homeassistant.components.recorder.statistics"]
    writer.async_add_external_statistics.assert_not_called()
    hass.config_entries.async_update_entry.assert_not_called()


    entry.data["_historical_baseline_repair"]["status"] = "verified"
    with patch.dict(sys.modules, modules):
        coordinator._publish_dated_statistics(date(2026, 10, 11), date(2026, 10, 12))
    writer.async_add_external_statistics.assert_called_once()
    rows = writer.async_add_external_statistics.call_args.args[2]
    assert [row["state"] for row in rows] == [0.9, 0.2]
    assert [row["sum"] for row in rows] == [1.9, 2.1]
    persisted = hass.config_entries.async_update_entry.call_args.kwargs["data"]
    assert persisted["_dated_statistics_daily_ledger"]["2026-10-12"] == 0.2

    entry.data.update(persisted)
    with patch.dict(sys.modules, modules):
        coordinator._publish_dated_statistics(date(2026, 10, 11), date(2026, 10, 12))
    writer.async_add_external_statistics.assert_called_once()

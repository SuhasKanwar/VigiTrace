"""Timeline normalization: moving recorder time onto the reference clock.

The sign of the correction is the whole point. Drift is recorder-minus-host, so
a recorder running fast has its timestamps pulled *back*; getting this backwards
would silently double the error instead of removing it.
"""

from datetime import datetime, timedelta, timezone

import pytest

from services.normalization import corrected_span, normalize_index, summarize_coverage
from tests import factories
from models.recording import RecordingIndex, TimeSpan

BASE = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)


def test_a_recorder_running_fast_has_its_timestamps_pulled_back():
    span = TimeSpan(start=BASE, end=BASE + timedelta(hours=1))

    corrected = corrected_span(span, 120.0)

    assert corrected.start == BASE - timedelta(seconds=120)
    assert corrected.end == BASE + timedelta(hours=1) - timedelta(seconds=120)


def test_a_recorder_running_slow_has_its_timestamps_pushed_forward():
    span = TimeSpan(start=BASE, end=BASE + timedelta(hours=1))

    corrected = corrected_span(span, -90.0)

    assert corrected.start == BASE + timedelta(seconds=90)


def test_duration_is_unchanged_by_correction():
    """Correcting an offset must not stretch or compress the segment."""
    span = TimeSpan(start=BASE, end=BASE + timedelta(hours=1))

    corrected = corrected_span(span, 3600.0)

    assert corrected.duration_seconds == span.duration_seconds


@pytest.mark.parametrize("drift", [None, 0.0])
def test_no_measured_drift_leaves_the_span_alone(drift):
    span = TimeSpan(start=BASE, end=BASE + timedelta(hours=1))

    assert corrected_span(span, drift) == span


def test_normalized_timeline_applies_the_devices_measured_drift():
    device = factories.device(drift_seconds=300.0)
    index = factories.index_with_gap()

    timeline = normalize_index(index, device)

    assert timeline["drift_seconds_applied"] == 300.0
    assert timeline["reference_clock"] == "probe host (UTC)"
    assert timeline["device_timezone"] == "CST-5:30:00"
    first = timeline["segments"][0]
    assert first["recorder_start"] == BASE.isoformat()
    assert first["normalized_start"] == (BASE - timedelta(seconds=300)).isoformat()


def test_segments_are_ordered_by_recorder_time():
    device = factories.device(drift_seconds=0.0)
    index = factories.index_with_gap()
    index.recordings.reverse()

    timeline = normalize_index(index, device)

    starts = [segment["recorder_start"] for segment in timeline["segments"]]
    assert starts == sorted(starts)


def test_gaps_are_reported_and_corrected_too():
    """A gap is a finding, so it carries the same clock correction as a segment."""
    device = factories.device(drift_seconds=300.0)
    index = factories.index_with_gap()

    timeline = normalize_index(index, device)

    assert timeline["gap_count"] == 1
    gap = timeline["gaps"][0]
    assert gap["channel_id"] == "1"
    assert gap["duration_seconds"] == 1800
    assert gap["start"] == (BASE + timedelta(hours=2) - timedelta(seconds=300)).isoformat()


def test_totals_come_from_the_index_not_from_the_segments_list():
    device = factories.device()
    index = factories.index_with_gap()

    timeline = normalize_index(index, device)

    assert timeline["segment_count"] == 3
    assert timeline["total_bytes"] == index.total_bytes == 649723904


def test_an_empty_index_normalizes_to_an_empty_timeline():
    timeline = normalize_index(RecordingIndex(), factories.device())

    assert timeline["segments"] == []
    assert timeline["gaps"] == []
    assert timeline["total_bytes"] == 0


def test_coverage_is_summarised_per_channel():
    index = factories.index_with_gap()
    index.recordings.append(
        factories.recording(
            "seg-4", BASE, BASE + timedelta(minutes=30), channel_id="2", size_bytes=100
        )
    )

    coverage = summarize_coverage(index)

    assert set(coverage) == {"1", "2"}
    assert coverage["1"]["segments"] == 3
    assert coverage["1"]["bytes"] == 649723904
    assert coverage["1"]["earliest"] == BASE.isoformat()
    assert coverage["1"]["latest"] == (BASE + timedelta(hours=3)).isoformat()
    assert coverage["2"]["segments"] == 1


def test_coverage_ignores_missing_sizes_rather_than_failing():
    index = RecordingIndex(
        recordings=[
            factories.recording("seg-1", BASE, BASE + timedelta(hours=1), size_bytes=None)
        ]
    )

    coverage = summarize_coverage(index)

    assert coverage["1"]["bytes"] == 0


def test_normalization_end_to_end_against_the_recorder(hik_client, hikvision_server):
    """The same correction, applied to an index the mock recorder produced."""
    from vendors.hikvision import HikvisionAdapter

    hikvision_server.clock_offset_seconds = 600.0
    adapter = HikvisionAdapter()
    device = adapter.identify(hik_client)
    index = adapter.search_recordings(
        hik_client,
        ["1"],
        datetime(2026, 9, 4, tzinfo=timezone.utc),
        datetime(2026, 9, 5, tzinfo=timezone.utc),
    )

    timeline = normalize_index(index, device)

    assert timeline["segment_count"] == 3
    assert timeline["gap_count"] == 1
    assert timeline["drift_seconds_applied"] == pytest.approx(600.0, abs=2.0)
    recorder_start = datetime.fromisoformat(timeline["segments"][0]["recorder_start"])
    normalized_start = datetime.fromisoformat(timeline["segments"][0]["normalized_start"])
    assert (recorder_start - normalized_start).total_seconds() == pytest.approx(600.0, abs=2.0)

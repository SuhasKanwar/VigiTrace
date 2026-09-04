"""Timeline normalization across channels and recorders.

Recorder clocks drift and are frequently set to local wall-clock time with no
timezone. Every recorder therefore carries a measured offset from the probing
host, and normalization applies that offset rather than assuming the device was
correct.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from models.device import StandardizedDevice
from models.recording import RecordingIndex, StandardizedRecording, TimeSpan


def corrected_span(span: TimeSpan, drift_seconds: float | None) -> TimeSpan:
    """Shift a span from recorder time onto the reference clock.

    Drift is defined as recorder-minus-host, so it is subtracted to move a
    recorder timestamp onto the reference timeline.
    """
    if not drift_seconds:
        return span
    delta = timedelta(seconds=drift_seconds)
    return TimeSpan(start=span.start - delta, end=span.end - delta)


def normalize_index(index: RecordingIndex, device: StandardizedDevice) -> dict[str, Any]:
    """Produce a corrected, ordered timeline plus the gaps between segments."""
    drift = device.clock.drift_seconds
    entries: list[dict[str, Any]] = []

    for recording in sorted(index.recordings, key=lambda r: r.span.start):
        adjusted = corrected_span(recording.span, drift)
        entries.append(
            {
                "recording_id": recording.recording_id,
                "channel_id": recording.channel_id,
                "recorder_start": recording.span.start.isoformat(),
                "recorder_end": recording.span.end.isoformat(),
                "normalized_start": adjusted.start.isoformat(),
                "normalized_end": adjusted.end.isoformat(),
                "duration_seconds": recording.span.duration_seconds,
                "codec": recording.codec,
                "size_bytes": recording.size_bytes,
                "event_type": recording.event_type,
            }
        )

    gaps: list[dict[str, Any]] = []
    for channel_id in sorted({r.channel_id for r in index.recordings}):
        for gap in index.gaps(channel_id):
            adjusted = corrected_span(gap, drift)
            gaps.append(
                {
                    "channel_id": channel_id,
                    "start": adjusted.start.isoformat(),
                    "end": adjusted.end.isoformat(),
                    "duration_seconds": gap.duration_seconds,
                }
            )

    return {
        "drift_seconds_applied": drift,
        "reference_clock": "probe host (UTC)",
        "device_timezone": device.clock.timezone,
        "segments": entries,
        # Gaps are where unindexed or deleted footage would sit, so they are
        # reported as findings rather than omitted.
        "gaps": gaps,
        "segment_count": len(entries),
        "gap_count": len(gaps),
        "total_bytes": index.total_bytes,
    }


def summarize_coverage(index: RecordingIndex) -> dict[str, Any]:
    """Per-channel coverage summary for the report module."""
    summary: dict[str, Any] = {}
    for recording in index.recordings:
        bucket = summary.setdefault(
            recording.channel_id,
            {"segments": 0, "bytes": 0, "earliest": None, "latest": None},
        )
        bucket["segments"] += 1
        bucket["bytes"] += recording.size_bytes or 0
        if bucket["earliest"] is None or recording.span.start < bucket["earliest"]:
            bucket["earliest"] = recording.span.start
        if bucket["latest"] is None or recording.span.end > bucket["latest"]:
            bucket["latest"] = recording.span.end

    for bucket in summary.values():
        for key in ("earliest", "latest"):
            if isinstance(bucket[key], datetime):
                bucket[key] = bucket[key].isoformat()
    return summary

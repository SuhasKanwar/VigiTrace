"""Builders for standardized objects that tests construct rather than probe.

Normalization, analysis and reporting all operate on an already-standardized
device, so those tests are better served by an object with exactly the values
under test than by a full probe against a mock recorder.
"""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from models.common import (
    Capability,
    Confidence,
    DeviceKind,
    ProbeMethod,
    Vendor,
    VendorFamily,
)
from models.device import (
    ChannelInfo,
    ClockInfo,
    DeviceIdentity,
    NetworkInfo,
    ProbeEvidence,
    RawArtifact,
    StandardizedDevice,
    StorageInfo,
)
from models.recording import RecordingIndex, StandardizedRecording, TimeSpan

PROBED_AT = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def artifact(endpoint: str, body: str, method: ProbeMethod = ProbeMethod.HIKVISION_ISAPI):
    return RawArtifact(
        endpoint=endpoint,
        method=method,
        status_code=200,
        content_type="application/xml",
        body=body,
        sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        retrieved_at=PROBED_AT,
    )


def evidence(
    method: ProbeMethod = ProbeMethod.HIKVISION_ISAPI,
    warnings: list[str] | None = None,
    artifacts: list[RawArtifact] | None = None,
) -> ProbeEvidence:
    return ProbeEvidence(
        method=method,
        started_at=PROBED_AT,
        finished_at=PROBED_AT + timedelta(milliseconds=250),
        duration_ms=250,
        endpoints_attempted=["/ISAPI/System/deviceInfo"],
        endpoints_succeeded=["/ISAPI/System/deviceInfo"],
        warnings=warnings or [],
        artifacts=artifacts if artifacts is not None else [artifact("/a", "<A/>")],
    )


def device(
    drift_seconds: float | None = 0.0,
    storage: list[StorageInfo] | None = None,
    serial_number: str | None = "DS-7208-SERIAL",
    confidence: Confidence = Confidence.CONFIRMED,
    ntp_enabled: bool | None = True,
    vendor: Vendor = Vendor.HIKVISION,
    family: VendorFamily = VendorFamily.HIKVISION,
    warnings: list[str] | None = None,
    timezone_name: str | None = "CST-5:30:00",
) -> StandardizedDevice:
    """A standardized device with only the fields a test cares about set."""
    return StandardizedDevice(
        identity=DeviceIdentity(
            vendor=vendor,
            family=family,
            confidence=confidence,
            kind=DeviceKind.DVR,
            model_name="DS-7208HQHI-K1",
            serial_number=serial_number,
            firmware_version="V4.30.005",
            mac_address="44:19:b6:6d:24:85",
            device_name="Embedded Net DVR",
        ),
        network=NetworkInfo(host="192.0.2.10", http_port=80, sdk_port=8000),
        channels=[
            ChannelInfo(channel_id="1", name="Front Gate", enabled=True, is_analog=True),
            ChannelInfo(channel_id="2", name="Reception", enabled=True, is_analog=True),
        ],
        storage=storage if storage is not None else [healthy_disk()],
        clock=ClockInfo(
            device_time=PROBED_AT + timedelta(seconds=drift_seconds or 0),
            device_time_raw="2026-09-04T12:00:00Z",
            timezone=timezone_name,
            ntp_enabled=ntp_enabled,
            ntp_servers=["pool.ntp.org"],
            probed_at=PROBED_AT,
            drift_seconds=drift_seconds,
        ),
        capabilities=[Capability.IDENTIFY, Capability.SEARCH_RECORDINGS],
        evidence=evidence(warnings=warnings),
        raw={"/ISAPI/System/deviceInfo": {"model": "DS-7208HQHI-K1"}},
    )


def healthy_disk() -> StorageInfo:
    return StorageInfo(
        storage_id="1",
        name="hde1",
        kind="SATA",
        status="ok",
        capacity_bytes=2000398843904,
        free_bytes=400000000000,
        device_property="RW",
    )


def failed_disk() -> StorageInfo:
    """A disk the recorder itself reports as failing."""
    return StorageInfo(
        storage_id="2",
        name="hde2",
        kind="SATA",
        status="smartFailed",
        capacity_bytes=2000398843904,
        free_bytes=1000000000000,
        device_property="RW",
    )


def nearly_full_disk() -> StorageInfo:
    """Under five percent free: the ring buffer is overwriting old footage."""
    return StorageInfo(
        storage_id="3",
        name="hde3",
        kind="SATA",
        status="ok",
        capacity_bytes=1_000_000_000_000,
        free_bytes=10_000_000_000,
        device_property="RW",
    )


def recording(
    recording_id: str,
    start: datetime,
    end: datetime,
    channel_id: str = "1",
    size_bytes: int | None = 1024,
    overwrite_count: int | None = None,
    **extra: Any,
) -> StandardizedRecording:
    return StandardizedRecording(
        recording_id=recording_id,
        channel_id=channel_id,
        span=TimeSpan(start=start, end=end),
        codec="H.264-BP",
        size_bytes=size_bytes,
        overwrite_count=overwrite_count,
        source_method=ProbeMethod.HIKVISION_ISAPI,
        **extra,
    )


def index_with_gap(channel_id: str = "1") -> RecordingIndex:
    """Two hours of footage, a 30-minute hole, then another half hour."""
    base = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    return RecordingIndex(
        recordings=[
            recording("seg-1", base, base + timedelta(hours=1), channel_id, 260358144),
            recording(
                "seg-2",
                base + timedelta(hours=1),
                base + timedelta(hours=2),
                channel_id,
                259817472,
            ),
            recording(
                "seg-3",
                base + timedelta(hours=2, minutes=30),
                base + timedelta(hours=3),
                channel_id,
                129548288,
                overwrite_count=5,
            ),
        ],
        searched_span=TimeSpan(start=base, end=base + timedelta(hours=4)),
        channels_searched=[channel_id],
    )

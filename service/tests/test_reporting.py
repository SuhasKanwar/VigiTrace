"""Report assembly.

The limitations section is the part that matters: a report that overstates what
a network acquisition establishes is worse than no report, so the tests focus on
whether the caveats appear when the underlying condition holds.
"""

from datetime import datetime, timezone

from models.common import Confidence, Vendor, VendorFamily
from models.recording import AcquisitionResult, TimeSpan
from services.reporting import REPORT_VERSION, build_report
from tests import factories


def acquisition() -> AcquisitionResult:
    return AcquisitionResult(
        recording_id="rec-1",
        channel_id="1",
        span=TimeSpan(
            start=datetime(2026, 9, 4, 8, tzinfo=timezone.utc),
            end=datetime(2026, 9, 4, 9, tzinfo=timezone.utc),
        ),
        stored_path="/evidence/ch1.bin",
        size_bytes=4096,
        md5="0" * 32,
        sha256="1" * 64,
        container="MPEG-PS (Hikvision IMKH)",
        acquired_at=datetime(2026, 9, 4, 12, tzinfo=timezone.utc),
        duration_ms=120,
        source_uri="rtsp://192.0.2.10/Streaming/tracks/101/",
    )


def test_a_report_describes_the_device_and_its_method():
    report = build_report(factories.device(), case_reference="CASE-1", examiner="P. Saluja")

    assert report["report_version"] == REPORT_VERSION
    assert report["case_reference"] == "CASE-1"
    assert report["examiner"] == "P. Saluja"
    assert report["device"]["serial_number"] == "DS-7208-SERIAL"
    assert report["method"]["probe_method"] == "HIKVISION_ISAPI"
    assert "ISAPI" in report["method"]["adapter_basis"]
    assert report["channels"]["total"] == 2


def test_the_evidence_digest_ties_the_report_to_the_retained_payloads():
    device = factories.device()

    report = build_report(device)

    assert report["integrity"]["evidence_digest_sha256"] == device.evidence.combined_sha256
    assert report["integrity"]["retained_artifacts"][0]["endpoint"] == "/a"


def test_hash_limitations_are_always_stated():
    report = build_report(factories.device())

    assert any(
        "do not establish that the acquisition itself was performed correctly" in note
        for note in report["limitations"]
    )
    assert any("No forensic disk image" in note for note in report["limitations"])


def test_an_inferred_vendor_attribution_is_caveated():
    report = build_report(
        factories.device(
            confidence=Confidence.PROBABLE,
            vendor=Vendor.GODREJ,
            family=VendorFamily.XIONGMAI,
        )
    )

    assert any("attribution for this device is PROBABLE" in n for n in report["limitations"])
    assert "XiongMai" in report["method"]["adapter_basis"]


def test_an_unmeasured_clock_is_caveated():
    report = build_report(factories.device(drift_seconds=None))

    assert any("clock offset could not be measured" in n for n in report["limitations"])


def test_a_measured_offset_is_stated_with_its_magnitude():
    report = build_report(factories.device(drift_seconds=125.0))

    assert any("measured offset of 125.00s" in n for n in report["limitations"])


def test_disabled_ntp_is_caveated():
    report = build_report(factories.device(ntp_enabled=False))

    assert any("NTP synchronisation is disabled" in n for n in report["limitations"])


def test_a_report_without_media_says_so():
    report = build_report(factories.device())

    assert any("No media was exported" in n for n in report["limitations"])


def test_a_report_with_media_carries_its_integrity_material():
    report = build_report(factories.device(), acquisitions=[acquisition()])

    assert report["acquisitions"][0]["sha256"] == "1" * 64
    assert not any("No media was exported" in n for n in report["limitations"])


def test_probe_warnings_are_promoted_into_the_limitations():
    report = build_report(factories.device(warnings=["InputProxy channels unavailable."]))

    assert "Probe warning: InputProxy channels unavailable." in report["limitations"]


def test_an_index_brings_a_timeline_and_coverage():
    report = build_report(factories.device(drift_seconds=60.0), index=factories.index_with_gap())

    assert report["recording_index"]["segment_count"] == 3
    assert report["timeline"]["gap_count"] == 1
    assert report["coverage"]["1"]["segments"] == 3


def test_a_vendor_without_an_adapter_is_reported_honestly():
    report = build_report(factories.device(vendor=Vendor.UNKNOWN, family=VendorFamily.UNKNOWN))

    assert report["method"]["adapter_basis"] == "No adapter is registered for this vendor."
    assert report["method"]["adapter_capabilities"] == []


def test_the_report_endpoint_returns_the_assembled_document(api_client):
    response = api_client.post(
        "/api/reports/generate",
        json={
            "device": factories.device().model_dump(mode="json"),
            "index": factories.index_with_gap().model_dump(mode="json"),
            "acquisitions": [acquisition().model_dump(mode="json")],
            "findings": [{"severity": "INFO", "title": "Nothing of note"}],
            "custody": [{"event": "acquired", "actor": "service"}],
            "case_reference": "CASE-2",
        },
    )
    body = response.json()

    assert response.status_code == 200
    assert body["success"] is True
    assert body["data"]["report"]["case_reference"] == "CASE-2"
    assert body["data"]["report"]["chain_of_custody"] == [
        {"event": "acquired", "actor": "service"}
    ]
    assert body["message"] == f"Generated report version {REPORT_VERSION}."

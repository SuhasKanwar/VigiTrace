"""Standardized report assembly.

A report states what was observed, how it was obtained, and what the method
cannot support. The limitations section is not boilerplate: an examiner reading
this later needs to know that a hash proves storage integrity but says nothing
about whether the acquisition itself was performed correctly, and that some
vendor attributions are inferred rather than vendor-confirmed.
"""

from datetime import datetime, timezone
from typing import Any

from models.device import StandardizedDevice
from models.recording import AcquisitionResult, RecordingIndex
from services.normalization import normalize_index, summarize_coverage
from vendors.registry import adapter_for

REPORT_VERSION = "1.0"


def _method_statement(device: StandardizedDevice) -> dict[str, Any]:
    """How the evidence was obtained, in terms a reviewer can challenge."""
    try:
        adapter = adapter_for(device.identity.vendor)
        provenance = adapter.provenance
        capabilities = sorted(c.value for c in adapter.capabilities)
    except KeyError:
        provenance = "No adapter is registered for this vendor."
        capabilities = []

    return {
        "vendor": device.identity.vendor.value,
        "family": device.identity.family.value,
        "attribution_confidence": device.identity.confidence.value,
        "probe_method": device.evidence.method.value,
        "adapter_basis": provenance,
        "adapter_capabilities": capabilities,
        "endpoints_attempted": device.evidence.endpoints_attempted,
        "endpoints_succeeded": device.evidence.endpoints_succeeded,
        "acquisition_window": {
            "started_at": device.evidence.started_at.isoformat(),
            "finished_at": device.evidence.finished_at.isoformat(),
            "duration_ms": device.evidence.duration_ms,
        },
    }


def _limitations(device: StandardizedDevice, has_acquisition: bool) -> list[str]:
    """State plainly what this report does not establish."""
    notes = [
        "Hashes establish that stored artifacts are byte-identical to what was received. "
        "They do not establish that the acquisition itself was performed correctly.",
        "Evidence was acquired over the network from a live recorder. No forensic disk image "
        "was taken, so deleted or unindexed footage residing in unallocated blocks is out of scope.",
    ]

    if device.identity.confidence.value != "CONFIRMED":
        notes.append(
            f"Vendor attribution for this device is {device.identity.confidence.value}, derived from "
            "device fingerprints rather than vendor-published documentation."
        )
    if device.clock.drift_seconds is None:
        notes.append(
            "The recorder's clock offset could not be measured, so recorded timestamps carry an "
            "unknown error relative to the reference clock."
        )
    elif abs(device.clock.drift_seconds) > 0:
        notes.append(
            f"Recorder timestamps carry a measured offset of {device.clock.drift_seconds:.2f}s. "
            "Normalized times in this report have been corrected; the recorder's own exports and "
            "on-screen burn-in have not."
        )
    if device.clock.ntp_enabled is False:
        notes.append(
            "NTP synchronisation is disabled on this recorder, so clock drift accumulates and the "
            "measured offset applies only at the time of the probe."
        )
    if not has_acquisition:
        notes.append("No media was exported; this report covers identification and indexing only.")
    if device.evidence.warnings:
        notes.extend(f"Probe warning: {warning}" for warning in device.evidence.warnings)
    return notes


def build_report(
    device: StandardizedDevice,
    index: RecordingIndex | None = None,
    acquisitions: list[AcquisitionResult] | None = None,
    findings: list[dict[str, Any]] | None = None,
    custody: list[dict[str, Any]] | None = None,
    case_reference: str | None = None,
    examiner: str | None = None,
) -> dict[str, Any]:
    """Assemble a complete, self-describing case report."""
    acquisitions = acquisitions or []
    generated_at = datetime.now(timezone.utc)

    report: dict[str, Any] = {
        "report_version": REPORT_VERSION,
        "generated_at": generated_at.isoformat(),
        "case_reference": case_reference,
        "examiner": examiner,
        "device": {
            "vendor": device.identity.vendor.value,
            "family": device.identity.family.value,
            "kind": device.identity.kind.value,
            "model": device.identity.model_name,
            "serial_number": device.identity.serial_number,
            "firmware_version": device.identity.firmware_version,
            "hardware_version": device.identity.hardware_version,
            "mac_address": device.identity.mac_address,
            "device_name": device.identity.device_name,
            "host": device.network.host,
            "http_port": device.network.http_port,
        },
        "channels": {
            "total": len(device.channels),
            "analog": device.analog_channel_count,
            "digital": device.digital_channel_count,
            "detail": [c.model_dump(mode="json") for c in device.channels],
        },
        "storage": {
            "total_capacity_bytes": device.total_capacity_bytes,
            "detail": [s.model_dump(mode="json") for s in device.storage],
        },
        "clock": device.clock.model_dump(mode="json"),
        "method": _method_statement(device),
        "integrity": {
            # One digest over every retained vendor response, so the report can be
            # checked against the raw material it was derived from.
            "evidence_digest_sha256": device.evidence.combined_sha256,
            "retained_artifacts": [
                {
                    "endpoint": a.endpoint,
                    "sha256": a.sha256,
                    "retrieved_at": a.retrieved_at.isoformat(),
                    "bytes": len(a.body.encode("utf-8", "replace")),
                }
                for a in device.evidence.artifacts
            ],
        },
        "acquisitions": [
            {
                "recording_id": a.recording_id,
                "channel_id": a.channel_id,
                "stored_path": a.stored_path,
                "size_bytes": a.size_bytes,
                "md5": a.md5,
                "sha256": a.sha256,
                "container": a.container,
                "acquired_at": a.acquired_at.isoformat(),
                "source_uri": a.source_uri,
                "warnings": a.warnings,
            }
            for a in acquisitions
        ],
        "findings": findings or [],
        "chain_of_custody": custody or [],
        "limitations": _limitations(device, bool(acquisitions)),
    }

    if index is not None:
        report["recording_index"] = {
            "segment_count": len(index.recordings),
            "total_bytes": index.total_bytes,
            "truncated": index.truncated,
            "warnings": index.warnings,
        }
        report["timeline"] = normalize_index(index, device)
        report["coverage"] = summarize_coverage(index)

    return report

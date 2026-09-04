"""Probe orchestration.

This module owns the sequence - connect, detect, identify, search, acquire -
and the mapping from internal failures onto the stable error envelope the
VigiTrace server proxies to the client. The service holds no state and stores
no credentials; persistence is the server's responsibility.
"""

import os
import re
import uuid
from datetime import datetime, timezone

from config import EVIDENCE_DIR
from models.common import Confidence, ErrorCode, Vendor
from models.probe import (
    AcquisitionRequest,
    AcquisitionResponse,
    DetectionResult,
    DeviceTarget,
    ProbeResponse,
    RecordingSearchRequest,
    RecordingSearchResponse,
    ServiceError,
)
from utils.logger import logger
from vendors.base import AdapterError
from vendors.registry import adapter_for, detect
from vendors.transports.http_digest import HttpDeviceClient, TransportError

_UNSAFE_PATH = re.compile(r"[^A-Za-z0-9._-]+")


def _client(target: DeviceTarget) -> HttpDeviceClient:
    credentials = target.credentials
    return HttpDeviceClient(
        host=target.host,
        port=target.http_port,
        username=credentials.username if credentials else None,
        password=credentials.password if credentials else None,
        use_https=target.use_https,
        timeout=target.timeout_seconds,
        verify_tls=target.verify_tls,
        sdk_port=target.sdk_port,
    )


def _error(exc: Exception) -> ServiceError:
    """Map an internal failure onto a stable, actionable envelope."""
    if isinstance(exc, TransportError):
        remediation = {
            ErrorCode.UNREACHABLE: "Confirm the recorder is powered on and reachable from this host.",
            ErrorCode.TIMEOUT: "Increase the timeout or check for a firewall between host and recorder.",
            ErrorCode.AUTH_FAILED: "Verify the username and password for this recorder.",
            ErrorCode.AUTH_LOCKOUT_RISK: (
                "Stop retrying. This recorder locks accounts after repeated failures; "
                "confirm the credentials out of band before trying again."
            ),
        }.get(exc.code)
        return ServiceError(
            code=exc.code, message=exc.message, detail=exc.detail, remediation=remediation
        )
    if isinstance(exc, AdapterError):
        return ServiceError(code=exc.code, message=exc.message, detail=exc.detail)
    logger.exception("Unhandled probe failure")
    return ServiceError(
        code=ErrorCode.INTERNAL,
        message="The service failed while probing the recorder.",
        detail=str(exc),
    )


def detect_device(target: DeviceTarget) -> ProbeResponse:
    """Fingerprint a recorder without committing to a full identification."""
    try:
        with _client(target) as client:
            result = detect(client, target.vendor_hint)
    except Exception as exc:
        return ProbeResponse(
            success=False, message="Vendor detection failed.", error=_error(exc)
        )

    if result.vendor == Vendor.UNKNOWN:
        return ProbeResponse(
            success=False,
            message="No supported vendor was recognised at this address.",
            detection=result,
            error=ServiceError(
                code=ErrorCode.UNSUPPORTED_VENDOR,
                message="The device did not match any registered vendor adapter.",
                detail=f"Candidates considered: {', '.join(result.candidates) or 'none'}.",
                remediation="Confirm the address and port, or supply a vendor hint.",
            ),
        )

    return ProbeResponse(
        success=True,
        message=f"Detected {result.vendor.value} at {result.confidence} confidence.",
        detection=result,
    )


def identify_device(target: DeviceTarget) -> ProbeResponse:
    """Detect the vendor, then build the full standardized device object."""
    try:
        with _client(target) as client:
            detection: DetectionResult = detect(client, target.vendor_hint)
            if detection.vendor == Vendor.UNKNOWN:
                return ProbeResponse(
                    success=False,
                    message="No supported vendor was recognised at this address.",
                    detection=detection,
                    error=ServiceError(
                        code=ErrorCode.UNSUPPORTED_VENDOR,
                        message="The device did not match any registered vendor adapter.",
                        detail=f"Candidates considered: {', '.join(detection.candidates) or 'none'}.",
                    ),
                )

            if target.credentials is None:
                return ProbeResponse(
                    success=False,
                    message="Credentials are required to identify this recorder.",
                    detection=detection,
                    error=ServiceError(
                        code=ErrorCode.AUTH_FAILED,
                        message="Identification requires an authenticated session.",
                        remediation="Supply the recorder's username and password.",
                    ),
                )

            adapter = adapter_for(detection.vendor)
            device = adapter.identify(client)

            # Detection ran unauthenticated; if it was only probable, the
            # authenticated identification does not retroactively confirm the
            # brand for families that are inferred rather than declared.
            if detection.confidence == Confidence.PROBABLE.value:
                device.evidence.warnings.append(
                    f"Vendor detection was PROBABLE: {'; '.join(detection.signals)}"
                )

    except Exception as exc:
        return ProbeResponse(
            success=False, message="Device identification failed.", error=_error(exc)
        )

    return ProbeResponse(
        success=True,
        message=f"Identified {device.identity.vendor.value} device successfully.",
        device=device,
        detection=detection,
    )


def search_recordings(request: RecordingSearchRequest) -> RecordingSearchResponse:
    """Search a recorder's own recording index."""
    if request.end <= request.start:
        return RecordingSearchResponse(
            success=False,
            message="The search window is empty.",
            error=ServiceError(
                code=ErrorCode.PROTOCOL_ERROR,
                message="End time must be later than start time.",
            ),
        )
    try:
        with _client(request.target) as client:
            detection = detect(client, request.target.vendor_hint)
            if detection.vendor == Vendor.UNKNOWN:
                return RecordingSearchResponse(
                    success=False,
                    message="No supported vendor was recognised at this address.",
                    error=ServiceError(
                        code=ErrorCode.UNSUPPORTED_VENDOR,
                        message="The device did not match any registered vendor adapter.",
                    ),
                )
            adapter = adapter_for(detection.vendor)
            index = adapter.search_recordings(
                client,
                request.channel_ids,
                request.start,
                request.end,
                request.max_results,
            )
    except Exception as exc:
        return RecordingSearchResponse(
            success=False, message="Recording search failed.", error=_error(exc)
        )

    return RecordingSearchResponse(
        success=True,
        message=f"Found {len(index.recordings)} recording segment(s).",
        index=index,
    )


def acquire_recording(request: AcquisitionRequest) -> AcquisitionResponse:
    """Perform a controlled export and hash it on the way to disk."""
    os.makedirs(EVIDENCE_DIR, exist_ok=True)
    safe_channel = _UNSAFE_PATH.sub("_", request.channel_id) or "ch"
    destination = os.path.join(
        EVIDENCE_DIR,
        f"{safe_channel}_{request.start:%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:8]}.bin",
    )

    try:
        with _client(request.target) as client:
            detection = detect(client, request.target.vendor_hint)
            if detection.vendor == Vendor.UNKNOWN:
                return AcquisitionResponse(
                    success=False,
                    message="No supported vendor was recognised at this address.",
                    error=ServiceError(
                        code=ErrorCode.UNSUPPORTED_VENDOR,
                        message="The device did not match any registered vendor adapter.",
                    ),
                )
            adapter = adapter_for(detection.vendor)
            result = adapter.download_recording(
                client,
                destination,
                request.recording_id,
                request.channel_id,
                request.start,
                request.end,
                playback_uri=request.playback_uri,
                file_path=request.file_path,
            )
    except Exception as exc:
        # Never leave a partial export behind masquerading as evidence.
        if os.path.exists(destination):
            try:
                os.remove(destination)
            except OSError:
                logger.warning("Could not remove partial acquisition at %s", destination)
        return AcquisitionResponse(
            success=False, message="Acquisition failed.", error=_error(exc)
        )

    logger.info(
        "Acquired %s bytes for channel %s (sha256=%s)",
        result.size_bytes,
        result.channel_id,
        result.sha256,
    )
    return AcquisitionResponse(
        success=True,
        message=f"Acquired {result.size_bytes} bytes and recorded integrity hashes.",
        acquisition=result,
    )

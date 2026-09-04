"""Request/response envelopes exchanged with the VigiTrace server."""

from datetime import datetime

from pydantic import Field

from models.common import Capability, ErrorCode, ProbeMethod, Vendor
from models.device import StandardizedDevice, VigiTraceModel
from models.recording import AcquisitionResult, RecordingIndex


class DeviceCredentials(VigiTraceModel):
    """Credentials are passed per-request and never persisted by the service.

    The service is stateless by design; the server owns storage and encryption.
    """

    username: str
    password: str


class DeviceTarget(VigiTraceModel):
    host: str
    http_port: int = 80
    use_https: bool = False
    credentials: DeviceCredentials | None = None
    vendor_hint: Vendor | None = Field(
        default=None,
        description="Optional operator assertion; detection still runs and may disagree.",
    )
    sdk_port: int | None = Field(
        default=None,
        description="Override for the vendor private-protocol port "
        "(Hikvision 8000, Dahua 37777, XiongMai 34567) when it has been moved.",
    )
    timeout_seconds: float = 8.0
    verify_tls: bool = False


class DetectionResult(VigiTraceModel):
    vendor: Vendor
    family: str
    confidence: str
    method: ProbeMethod
    signals: list[str] = Field(default_factory=list)
    candidates: list[str] = Field(default_factory=list)
    detected_at: datetime


class ServiceError(VigiTraceModel):
    code: ErrorCode
    message: str
    detail: str | None = None
    remediation: str | None = None


class ProbeResponse(VigiTraceModel):
    success: bool
    message: str
    device: StandardizedDevice | None = None
    detection: DetectionResult | None = None
    error: ServiceError | None = None


class CapabilityReport(VigiTraceModel):
    vendor: Vendor
    family: str
    capabilities: list[Capability]
    notes: list[str] = Field(default_factory=list)


class RecordingSearchRequest(VigiTraceModel):
    target: DeviceTarget
    channel_ids: list[str] = Field(default_factory=list)
    start: datetime
    end: datetime
    max_results: int = 200


class RecordingSearchResponse(VigiTraceModel):
    success: bool
    message: str
    index: RecordingIndex | None = None
    error: ServiceError | None = None


class AcquisitionRequest(VigiTraceModel):
    target: DeviceTarget
    recording_id: str
    channel_id: str
    start: datetime
    end: datetime
    playback_uri: str | None = None
    file_path: str | None = None


class AcquisitionResponse(VigiTraceModel):
    success: bool
    message: str
    acquisition: AcquisitionResult | None = None
    error: ServiceError | None = None

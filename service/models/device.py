"""The standardized device object every vendor adapter collapses into.

The README's adapter contract is explicit that normalization must not destroy
provenance: translate manufacturer-specific formats into a common evidence
model *without hiding original metadata*. Every model here therefore carries
the verbatim vendor payload alongside the normalized view, and records how each
fact was obtained.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from models.common import (
    Capability,
    Confidence,
    DeviceKind,
    ProbeMethod,
    Vendor,
    VendorFamily,
)


class VigiTraceModel(BaseModel):
    """Base model: reject unknown fields so vendor drift surfaces loudly."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)


class DeviceIdentity(VigiTraceModel):
    vendor: Vendor = Vendor.UNKNOWN
    family: VendorFamily = VendorFamily.UNKNOWN
    confidence: Confidence = Confidence.UNKNOWN
    kind: DeviceKind = DeviceKind.UNKNOWN
    model_name: str | None = Field(default=None, description="Marketing/model string.")
    serial_number: str | None = None
    firmware_version: str | None = None
    firmware_released: str | None = None
    hardware_version: str | None = None
    mac_address: str | None = None
    device_name: str | None = None


class NetworkInfo(VigiTraceModel):
    host: str
    http_port: int = 80
    https_port: int | None = None
    rtsp_port: int | None = None
    sdk_port: int | None = Field(
        default=None,
        description="Vendor private-protocol port (Hikvision 8000, Dahua 37777, XiongMai 34567).",
    )
    mac_address: str | None = None
    ipv4_address: str | None = None
    subnet_mask: str | None = None
    gateway: str | None = None
    dhcp_enabled: bool | None = None


class ChannelInfo(VigiTraceModel):
    channel_id: str
    name: str | None = None
    enabled: bool | None = None
    is_analog: bool | None = None
    codec: str | None = None
    resolution: str | None = None
    track_id: str | None = Field(
        default=None,
        description="Vendor track identifier used for recording search (Hikvision uses 101 for ch1 main).",
    )


class StorageInfo(VigiTraceModel):
    storage_id: str
    name: str | None = None
    kind: str | None = None
    status: str | None = None
    capacity_bytes: int | None = None
    free_bytes: int | None = None
    device_property: str | None = Field(
        default=None, description="Read/write posture, e.g. RW, RO, Redund."
    )

    @property
    def used_bytes(self) -> int | None:
        if self.capacity_bytes is None or self.free_bytes is None:
            return None
        return max(self.capacity_bytes - self.free_bytes, 0)


class ClockInfo(VigiTraceModel):
    """Recorder clock state.

    ``drift_seconds`` is the recorder's clock minus the probing host's clock at
    the moment of the probe. Every downstream timeline claim depends on it, so
    it is captured at identify time rather than recomputed later.
    """

    device_time: datetime | None = None
    device_time_raw: str | None = None
    timezone: str | None = None
    ntp_enabled: bool | None = None
    ntp_servers: list[str] = Field(default_factory=list)
    probed_at: datetime | None = None
    drift_seconds: float | None = None


class RawArtifact(VigiTraceModel):
    """One verbatim vendor response, retained for provenance and hashing."""

    endpoint: str
    method: ProbeMethod
    status_code: int | None = None
    content_type: str | None = None
    body: str
    sha256: str
    retrieved_at: datetime


class ProbeEvidence(VigiTraceModel):
    """The audit trail of how this object was produced."""

    method: ProbeMethod
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    endpoints_attempted: list[str] = Field(default_factory=list)
    endpoints_succeeded: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    artifacts: list[RawArtifact] = Field(default_factory=list)

    @property
    def combined_sha256(self) -> str:
        import hashlib

        digest = hashlib.sha256()
        for artifact in sorted(self.artifacts, key=lambda a: a.endpoint):
            digest.update(artifact.sha256.encode("ascii"))
        return digest.hexdigest()


class StandardizedDevice(VigiTraceModel):
    """The single shape the rest of the pipeline operates on."""

    identity: DeviceIdentity
    network: NetworkInfo
    channels: list[ChannelInfo] = Field(default_factory=list)
    storage: list[StorageInfo] = Field(default_factory=list)
    clock: ClockInfo = Field(default_factory=ClockInfo)
    capabilities: list[Capability] = Field(default_factory=list)
    evidence: ProbeEvidence
    raw: dict[str, Any] = Field(
        default_factory=dict,
        description="Verbatim per-endpoint vendor payloads. Never pruned.",
    )

    @property
    def analog_channel_count(self) -> int:
        return sum(1 for c in self.channels if c.is_analog is True)

    @property
    def digital_channel_count(self) -> int:
        return sum(1 for c in self.channels if c.is_analog is False)

    @property
    def total_capacity_bytes(self) -> int:
        return sum(s.capacity_bytes or 0 for s in self.storage)

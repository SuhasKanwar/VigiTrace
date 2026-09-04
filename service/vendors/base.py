"""The vendor adapter contract.

An adapter is responsible for one protocol lineage, not one brand. It declares
what it can genuinely do via ``capabilities``; the pipeline consults that and
skips stages the device cannot support rather than emitting an empty result
that looks like a real one.
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import ClassVar

from models.common import (
    Capability,
    Confidence,
    ErrorCode,
    ProbeMethod,
    Vendor,
    VendorFamily,
)
from models.device import ProbeEvidence, StandardizedDevice
from models.recording import AcquisitionResult, RecordingIndex
from vendors.transports.http_digest import HttpDeviceClient, TransportError


class AdapterError(Exception):
    """A vendor-level failure that is not a transport failure."""

    def __init__(self, code: ErrorCode, message: str, detail: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


class Fingerprint:
    """An unauthenticated identification attempt.

    ``score`` is 0-100. Anything above zero means at least one positive signal;
    the detector picks the highest scorer and records every signal that fired so
    an investigator can see why a vendor was chosen.
    """

    def __init__(self, vendor: Vendor, score: int, signals: list[str]):
        self.vendor = vendor
        self.score = max(0, min(100, score))
        self.signals = signals

    def __repr__(self) -> str:
        return f"Fingerprint({self.vendor.value}, score={self.score}, signals={self.signals})"


class EvidenceRecorder:
    """Collects timing and artifacts so every probe carries its own audit trail."""

    def __init__(self, method: ProbeMethod):
        self.method = method
        self.started_at = datetime.now(timezone.utc)
        self.warnings: list[str] = []

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def finish(self, client: HttpDeviceClient | None = None) -> ProbeEvidence:
        finished_at = datetime.now(timezone.utc)
        return ProbeEvidence(
            method=self.method,
            started_at=self.started_at,
            finished_at=finished_at,
            duration_ms=int((finished_at - self.started_at).total_seconds() * 1000),
            endpoints_attempted=list(client.attempted) if client else [],
            endpoints_succeeded=list(client.succeeded) if client else [],
            warnings=self.warnings,
            artifacts=list(client.artifacts) if client else [],
        )


class VendorAdapter(ABC):
    """Base class for every vendor integration."""

    vendor: ClassVar[Vendor] = Vendor.UNKNOWN
    family: ClassVar[VendorFamily] = VendorFamily.UNKNOWN
    probe_method: ClassVar[ProbeMethod] = ProbeMethod.UNAUTHENTICATED_FINGERPRINT
    capabilities: ClassVar[frozenset[Capability]] = frozenset()
    default_http_port: ClassVar[int] = 80
    sdk_port: ClassVar[int | None] = None
    #: Human-readable basis for supporting this vendor, surfaced in reports.
    provenance: ClassVar[str] = ""
    #: Ceiling on how strongly this vendor may ever be asserted. Families
    #: identified by fingerprint rather than by vendor-published protocol cap
    #: themselves here so a high detection score cannot overstate the claim.
    max_confidence: ClassVar[Confidence] = Confidence.CONFIRMED

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    def require(self, capability: Capability) -> None:
        if not self.supports(capability):
            raise AdapterError(
                ErrorCode.CAPABILITY_UNAVAILABLE,
                f"{self.vendor.value} adapter does not support {capability.value}.",
                "This is a limitation of the vendor's published protocol, not a bug.",
            )

    @classmethod
    @abstractmethod
    def fingerprint(cls, client: HttpDeviceClient) -> Fingerprint:
        """Identify the device without authenticating."""

    @abstractmethod
    def identify(self, client: HttpDeviceClient) -> StandardizedDevice:
        """Produce the full standardized object for an authenticated device."""

    def search_recordings(
        self,
        client: HttpDeviceClient,
        channel_ids: list[str],
        start: datetime,
        end: datetime,
        max_results: int = 200,
    ) -> RecordingIndex:
        self.require(Capability.SEARCH_RECORDINGS)
        raise AdapterError(
            ErrorCode.CAPABILITY_UNAVAILABLE,
            f"{self.vendor.value} recording search is not implemented.",
        )

    def download_recording(
        self,
        client: HttpDeviceClient,
        destination: str,
        recording_id: str,
        channel_id: str,
        start: datetime,
        end: datetime,
        playback_uri: str | None = None,
        file_path: str | None = None,
    ) -> AcquisitionResult:
        self.require(Capability.DOWNLOAD_RECORDING)
        raise AdapterError(
            ErrorCode.CAPABILITY_UNAVAILABLE,
            f"{self.vendor.value} acquisition is not implemented.",
        )


def to_int(value: object) -> int | None:
    """Parse an int from vendor payloads that mix types, bases and whitespace.

    XiongMai reports storage sizes as hex strings ("0x001D1000"), so a plain
    ``int(float(...))`` drops them silently. Hex is handled explicitly rather
    than guessed at, and anything genuinely unparsable still returns None.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        negative = text.startswith("-")
        digits = text[1:] if negative else text
        if digits[:2].lower() == "0x":
            parsed = int(digits, 16)
            return -parsed if negative else parsed
        return int(float(text))
    except (TypeError, ValueError, OverflowError):
        # OverflowError covers "inf" and "1e400": this parser is fed unvalidated
        # vendor strings and must never raise out of a coercion helper.
        return None


def to_bool(value: object) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "on", "enable", "enabled"):
        return True
    if text in ("false", "0", "no", "off", "disable", "disabled"):
        return False
    return None


def mb_to_bytes(value: object) -> int | None:
    """Both vendor families report capacity in megabytes."""
    parsed = to_int(value)
    return parsed * 1024 * 1024 if parsed is not None else None

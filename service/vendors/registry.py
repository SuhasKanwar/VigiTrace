"""Adapter registry and vendor detection.

Detection runs every adapter's unauthenticated fingerprint and picks the
highest scorer. Ties and near-ties are reported rather than silently resolved,
because guessing a vendor wrong sends the whole downstream pipeline to the
wrong parser.
"""

from datetime import datetime, timezone

from models.common import VENDOR_FAMILY, Confidence, ErrorCode, ProbeMethod, Vendor, VendorFamily
from models.probe import DetectionResult
from vendors.base import Fingerprint, VendorAdapter
from vendors.cpplus import CpPlusAdapter
from vendors.dahua import DahuaAdapter
from vendors.godrej import GodrejAdapter
from vendors.hikvision import HikvisionAdapter
from vendors.transports.http_digest import HttpDeviceClient, TransportError

#: Order matters only for stable tie-breaking; scoring decides the winner.
ADAPTERS: tuple[type[VendorAdapter], ...] = (
    HikvisionAdapter,
    DahuaAdapter,
    CpPlusAdapter,
    GodrejAdapter,
)

_BY_VENDOR: dict[Vendor, type[VendorAdapter]] = {cls.vendor: cls for cls in ADAPTERS}

#: A fingerprint at or above this score is treated as a confirmed match.
CONFIDENT_SCORE = 70
#: Below this, no adapter is considered to have recognised the device.
MINIMUM_SCORE = 20
#: Two candidates within this margin are reported as ambiguous.
AMBIGUITY_MARGIN = 10


def adapter_for(vendor: Vendor) -> VendorAdapter:
    """Instantiate the adapter registered for a vendor."""
    cls = _BY_VENDOR.get(vendor)
    if cls is None:
        raise KeyError(f"No adapter registered for vendor {vendor.value}.")
    return cls()


def supported_vendors() -> list[dict]:
    """Describe the registry for the capability endpoint."""
    return [
        {
            "vendor": cls.vendor.value,
            "family": cls.family.value,
            "capabilities": sorted(c.value for c in cls.capabilities),
            "default_http_port": cls.default_http_port,
            "sdk_port": cls.sdk_port,
            "provenance": cls.provenance,
        }
        for cls in ADAPTERS
    ]


def detect(client: HttpDeviceClient, vendor_hint: Vendor | None = None) -> DetectionResult:
    """Fingerprint a device against every registered adapter.

    A caller-supplied hint is honoured only when the device does not contradict
    it; an operator's assertion does not override what the wire says.
    """
    results: list[Fingerprint] = []
    for cls in ADAPTERS:
        try:
            results.append(cls.fingerprint(client))
        except TransportError as exc:
            if exc.code in (ErrorCode.AUTH_FAILED, ErrorCode.AUTH_LOCKOUT_RISK):
                # Detection runs before credentials are offered, so a rejection
                # says the endpoint is real and guarded - a positive signal for
                # this adapter, and no reason to stop trying the others.
                results.append(
                    Fingerprint(
                        cls.vendor,
                        30,
                        [
                            f"{cls.vendor.value}: probe endpoint answered a credential "
                            f"challenge before the fingerprint could complete"
                        ],
                    )
                )
                continue
            # An unreachable or timing-out host fails identically for every
            # adapter, so there is nothing to learn from continuing.
            raise
        except Exception as exc:  # a broken adapter must not mask the others
            results.append(Fingerprint(cls.vendor, 0, [f"fingerprint raised {exc!r}"]))

    ranked = sorted(results, key=lambda f: f.score, reverse=True)
    best = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None

    signals = list(best.signals)
    candidates = [f"{f.vendor.value}={f.score}" for f in ranked if f.score > 0]

    if best.score < MINIMUM_SCORE:
        return DetectionResult(
            vendor=Vendor.UNKNOWN,
            family=VendorFamily.UNKNOWN.value,
            confidence=Confidence.UNKNOWN.value,
            method=ProbeMethod.UNAUTHENTICATED_FINGERPRINT,
            signals=signals or ["no adapter recognised this device"],
            candidates=candidates,
            detected_at=datetime.now(timezone.utc),
        )

    confidence = Confidence.CONFIRMED if best.score >= CONFIDENT_SCORE else Confidence.PROBABLE
    ceiling = _BY_VENDOR[best.vendor].max_confidence
    if confidence == Confidence.CONFIRMED and ceiling != Confidence.CONFIRMED:
        # A strong fingerprint still cannot promote a vendor past what its own
        # adapter says the evidence supports.
        confidence = ceiling
        signals.append(
            f"{best.vendor.value} attribution is capped at {ceiling.value}: "
            "identification is fingerprint-derived, not vendor-published"
        )
    if runner_up and best.score - runner_up.score <= AMBIGUITY_MARGIN and runner_up.score > 0:
        # Dahua and CP Plus legitimately score close together; say so instead of
        # presenting a coin-flip as a determination.
        confidence = Confidence.PROBABLE
        signals.append(
            f"ambiguous: {runner_up.vendor.value} scored {runner_up.score} "
            f"against {best.vendor.value}'s {best.score}"
        )

    if vendor_hint and vendor_hint != best.vendor:
        hinted = next((f for f in ranked if f.vendor == vendor_hint), None)
        if hinted and hinted.score >= MINIMUM_SCORE:
            signals.append(
                f"operator hint {vendor_hint.value} is plausible (score {hinted.score}) "
                f"but {best.vendor.value} scored higher"
            )
        else:
            signals.append(
                f"operator hint {vendor_hint.value} contradicted by the device; ignored"
            )

    return DetectionResult(
        vendor=best.vendor,
        family=VENDOR_FAMILY.get(best.vendor, VendorFamily.UNKNOWN).value,
        confidence=confidence.value,
        method=_BY_VENDOR[best.vendor].probe_method,
        signals=signals,
        candidates=candidates,
        detected_at=datetime.now(timezone.utc),
    )

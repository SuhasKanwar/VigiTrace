"""CP Plus adapter.

CP Plus (Aditya Infotech, India) recorders run Dahua firmware. The evidence is
code-level rather than documentary: CP Plus SmartPlayer binaries export Dahua
C++ symbols (``Dahua::StreamPackage::CFlvPacket::InputData``,
``??0CMutex@Infra@Dahua@@``), ship the ``DAV Video File(*.dav)`` filter, and CP
Plus firmware advisories carry Dahua's exact version convention
(``V4.001.00AT009.0.R``). CP Plus publishes no acknowledgement of this, so the
relationship is inferred from artifacts, not from a vendor statement.

Consequently this adapter *inherits* the Dahua CGI implementation rather than
duplicating it, and only overrides identification and branding. CP Plus NVRs
additionally hold ONVIF Profile G conformance, which is recorded as a
capability note because a published standard is a more defensible acquisition
path than a reverse-engineered one.
"""

import re
from typing import ClassVar

from models.common import Confidence, Vendor, VendorFamily
from models.device import StandardizedDevice
from vendors.base import Fingerprint
from vendors.dahua import MAGICBOX, DahuaAdapter
from vendors.transports.http_digest import HttpDeviceClient

#: Dahua-lineage firmware built for CP Plus carries an 'AT' vendor token,
#: e.g. V4.001.00AT009.0.R - the clearest on-device CP Plus discriminator.
_CPPLUS_FIRMWARE_RE = re.compile(r"\d+\.\d+.*AT\d+", re.IGNORECASE)
_CPPLUS_TOKENS = ("cp plus", "cpplus", "cp-plus", "aditya")


class CpPlusAdapter(DahuaAdapter):
    vendor: ClassVar[Vendor] = Vendor.CPPLUS
    family: ClassVar[VendorFamily] = VendorFamily.DAHUA
    provenance: ClassVar[str] = (
        "CP Plus recorders run Dahua firmware (SmartPlayer binaries export Dahua:: "
        "symbols; firmware uses Dahua's V<x>AT<y> convention). Handled by the Dahua "
        "CGI adapter. CP Plus NVRs also hold ONVIF Profile G conformance."
    )
    #: Branding is inferred from firmware tokens, so detection may never
    #: promote CP Plus to CONFIRMED however strongly it scores.
    max_confidence: ClassVar[Confidence] = Confidence.PROBABLE
    #: ONVIF Profile G covers recording search and retrieval, and is a
    #: standards-based fallback if the CGI surface differs on a given model.
    onvif_profile_g: ClassVar[bool] = True

    @classmethod
    def fingerprint(cls, client: HttpDeviceClient) -> Fingerprint:
        """CP Plus looks exactly like Dahua until firmware or branding is read.

        The shared Dahua signals are inherited and then adjusted: a CP Plus
        branding or firmware token raises the score above plain Dahua, while its
        absence lowers it, so an unbranded Dahua unit is not mislabelled.
        """
        base = super().fingerprint(client)
        signals = list(base.signals)
        score = base.score

        branded = False
        for action in ("getVendor", "getSoftwareVersion", "getMachineName"):
            artifact = client.try_get(
                MAGICBOX, cls.probe_method, tolerate_auth_failure=True, action=action
            )
            if artifact is None or not artifact.body:
                continue
            body = artifact.body
            lowered = body.lower()
            if any(token in lowered for token in _CPPLUS_TOKENS):
                score += 25
                signals.append(f"magicBox.cgi?action={action} reports CP Plus branding")
                branded = True
                break
            if _CPPLUS_FIRMWARE_RE.search(body):
                score += 20
                signals.append(
                    f"firmware string from {action} uses the Dahua-for-CP-Plus 'AT' vendor token"
                )
                branded = True
                break

        if not branded and score:
            # Speaks Dahua CGI with nothing CP Plus about it - prefer plain Dahua.
            score = max(score - 20, 1)
            signals.append("no CP Plus branding found; plain Dahua is the better match")

        return Fingerprint(cls.vendor, score, signals)

    def identify(self, client: HttpDeviceClient) -> StandardizedDevice:
        device = super().identify(client)
        device.identity.vendor = self.vendor
        device.identity.family = self.family
        # Branding is inferred from firmware/CGI tokens rather than asserted by
        # the vendor, so identification stays PROBABLE even when the CGI answers.
        device.identity.confidence = Confidence.PROBABLE
        device.evidence.warnings.append(
            "CP Plus identified via Dahua firmware lineage; vendor publishes no "
            "protocol documentation of its own."
        )
        return device

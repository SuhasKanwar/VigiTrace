"""Shared enumerations for the VigiTrace evidence model.

Vendor/family mapping is research-derived, not assumed:
  * CP Plus recorders run Dahua firmware (CP Plus SmartPlayer binaries export
    ``Dahua::`` symbols; CP Plus firmware uses Dahua's ``V4.001.00AT009.0.R``
    version convention), so CP Plus belongs to the DAHUA family.
  * Godrej recorders are white-labelled XiongMai/Sofia units (DVRIP on TCP
    34567) and share nothing with the Hikvision or Dahua protocol stacks.
"""

from enum import Enum


class Vendor(str, Enum):
    """The badge on the front of the recorder."""

    HIKVISION = "HIKVISION"
    DAHUA = "DAHUA"
    CPPLUS = "CPPLUS"
    GODREJ = "GODREJ"
    UNKNOWN = "UNKNOWN"


class VendorFamily(str, Enum):
    """The protocol lineage the recorder actually speaks.

    Several badges share one lineage, which is why adapters key off the family
    rather than the brand.
    """

    HIKVISION = "HIKVISION"
    DAHUA = "DAHUA"
    XIONGMAI = "XIONGMAI"
    UNKNOWN = "UNKNOWN"


class DeviceKind(str, Enum):
    DVR = "DVR"
    NVR = "NVR"
    XVR = "XVR"
    HVR = "HVR"
    IPC = "IPC"
    UNKNOWN = "UNKNOWN"


class ProbeMethod(str, Enum):
    """How a fact about the device was obtained."""

    HIKVISION_ISAPI = "HIKVISION_ISAPI"
    DAHUA_CGI = "DAHUA_CGI"
    XIONGMAI_DVRIP = "XIONGMAI_DVRIP"
    ONVIF = "ONVIF"
    UNAUTHENTICATED_FINGERPRINT = "UNAUTHENTICATED_FINGERPRINT"


class Confidence(str, Enum):
    """How much weight an identification carries.

    CONFIRMED is reserved for facts an authenticated vendor API returned.
    PROBABLE covers unauthenticated fingerprints (digest realm shape, banner,
    open-port profile). Never report PROBABLE as fact in a forensic record.
    """

    CONFIRMED = "CONFIRMED"
    PROBABLE = "PROBABLE"
    UNKNOWN = "UNKNOWN"


class Capability(str, Enum):
    """What an adapter can genuinely do against a given family.

    Adapters declare these honestly; the pipeline skips stages a device cannot
    support rather than pretending they ran.
    """

    IDENTIFY = "IDENTIFY"
    ENUMERATE_CHANNELS = "ENUMERATE_CHANNELS"
    ENUMERATE_STORAGE = "ENUMERATE_STORAGE"
    READ_CLOCK = "READ_CLOCK"
    READ_NTP = "READ_NTP"
    SEARCH_RECORDINGS = "SEARCH_RECORDINGS"
    DOWNLOAD_RECORDING = "DOWNLOAD_RECORDING"
    READ_LOGS = "READ_LOGS"
    READ_USERS = "READ_USERS"


class DeviceState(str, Enum):
    """Server-owned lifecycle state.

    Progress states run REGISTERED -> ... -> VERIFIED. The four terminal
    failure states are distinguishable so an investigator can tell "wrong
    password" from "wrong vendor" from "cable unplugged".
    """

    REGISTERED = "REGISTERED"
    IDENTIFYING = "IDENTIFYING"
    IDENTIFIED = "IDENTIFIED"
    ENUMERATING = "ENUMERATING"
    ENUMERATED = "ENUMERATED"
    INDEXING = "INDEXING"
    INDEXED = "INDEXED"
    ACQUIRING = "ACQUIRING"
    ACQUIRED = "ACQUIRED"
    VERIFYING = "VERIFYING"
    VERIFIED = "VERIFIED"
    UNREACHABLE = "UNREACHABLE"
    AUTH_FAILED = "AUTH_FAILED"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


class ErrorCode(str, Enum):
    """Stable machine-readable failure reasons carried across the proxy."""

    UNREACHABLE = "UNREACHABLE"
    TIMEOUT = "TIMEOUT"
    AUTH_FAILED = "AUTH_FAILED"
    AUTH_LOCKOUT_RISK = "AUTH_LOCKOUT_RISK"
    UNSUPPORTED_VENDOR = "UNSUPPORTED_VENDOR"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    NOT_CONFIGURED = "NOT_CONFIGURED"
    #: The caller named an image this service cannot read. Distinct from
    #: NOT_CONFIGURED because nothing is misconfigured and nothing upstream
    #: failed: the path is simply wrong, which is the caller's to fix.
    IMAGE_UNREADABLE = "IMAGE_UNREADABLE"
    INTERNAL = "INTERNAL"


VENDOR_FAMILY: dict[Vendor, VendorFamily] = {
    Vendor.HIKVISION: VendorFamily.HIKVISION,
    Vendor.DAHUA: VendorFamily.DAHUA,
    Vendor.CPPLUS: VendorFamily.DAHUA,
    Vendor.GODREJ: VendorFamily.XIONGMAI,
    Vendor.UNKNOWN: VendorFamily.UNKNOWN,
}

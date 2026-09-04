"""Vendor adapters for DVR/NVR device families."""

from vendors.base import AdapterError, Fingerprint, VendorAdapter
from vendors.cpplus import CpPlusAdapter
from vendors.dahua import DahuaAdapter
from vendors.godrej import GodrejAdapter
from vendors.hikvision import HikvisionAdapter
from vendors.registry import ADAPTERS, adapter_for, detect, supported_vendors

__all__ = [
    "ADAPTERS",
    "AdapterError",
    "CpPlusAdapter",
    "DahuaAdapter",
    "Fingerprint",
    "GodrejAdapter",
    "HikvisionAdapter",
    "VendorAdapter",
    "adapter_for",
    "detect",
    "supported_vendors",
]

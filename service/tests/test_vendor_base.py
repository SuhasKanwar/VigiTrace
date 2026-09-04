"""The adapter contract and its shared coercion helpers.

Vendor payloads are strings with no schema, so these helpers decide whether a
capacity figure survives into evidence at all. They are worth testing directly
rather than only through an adapter.
"""

import pytest

from models.common import VENDOR_FAMILY, Capability, ErrorCode, Vendor, VendorFamily
from vendors.base import (
    AdapterError,
    EvidenceRecorder,
    Fingerprint,
    mb_to_bytes,
    to_bool,
    to_int,
)
from vendors.godrej import GodrejAdapter
from vendors.hikvision import HikvisionAdapter
from vendors.registry import ADAPTERS, supported_vendors


class TestIntegerCoercion:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("1907729", 1907729),
            (" 1907729 ", 1907729),
            (1907729, 1907729),
            ("1907729.0", 1907729),
            ("", None),
            (None, None),
            ("not a number", None),
            ([], None),
        ],
    )
    def test_values_seen_in_vendor_payloads(self, value, expected):
        assert to_int(value) == expected

    def test_hex_strings_are_parsed(self):
        """XiongMai reports partition sizes in hex, and they are storage figures.

        A dropped capacity is not a cosmetic loss: retention and overwrite
        pressure are assessed from it, so the value has to survive parsing.
        """
        assert to_int("0x001D1000") == 1904640
        assert to_int("0X001d1000") == 1904640
        assert to_int("-0x10") == -16

    @pytest.mark.parametrize("value, expected", [(True, 1), (False, 0), (-5, -5)])
    def test_native_types_pass_straight_through(self, value, expected):
        assert to_int(value) == expected

    @pytest.mark.parametrize("value", ["0x", "0xZZ", "nan-ish", "12abc"])
    def test_junk_is_still_rejected(self, value):
        """Widening the parser must not start inventing numbers from noise."""
        assert to_int(value) is None


class TestBooleanCoercion:
    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on", "enable", "enabled"])
    def test_affirmative_spellings(self, value):
        assert to_bool(value) is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "off", "disable", "disabled"])
    def test_negative_spellings(self, value):
        assert to_bool(value) is False

    @pytest.mark.parametrize("value", [None, "", "maybe"])
    def test_anything_else_is_unknown_not_false(self, value):
        """An unreadable flag must not be reported as a definite 'off'."""
        assert to_bool(value) is None


class TestMegabyteConversion:
    def test_both_families_report_capacity_in_megabytes(self):
        assert mb_to_bytes(1907729) == 1907729 * 1024 * 1024 == 2000398843904
        assert mb_to_bytes("102400") == 107374182400

    def test_zero_is_a_capacity_not_a_missing_value(self):
        assert mb_to_bytes(0) == 0

    def test_an_unreadable_figure_is_dropped(self):
        assert mb_to_bytes("n/a") is None
        assert mb_to_bytes(None) is None


class TestFingerprint:
    def test_scores_are_clamped_to_the_documented_range(self):
        assert Fingerprint(Vendor.CPPLUS, 120, []).score == 100
        assert Fingerprint(Vendor.DAHUA, -10, []).score == 0

    def test_signals_are_carried_verbatim(self):
        signals = ["digest realm is a bare MAC (4419b66d2485)"]

        assert Fingerprint(Vendor.HIKVISION, 45, signals).signals == signals

    def test_repr_names_the_vendor_and_score(self):
        assert "HIKVISION" in repr(Fingerprint(Vendor.HIKVISION, 45, []))


class TestCapabilityContract:
    def test_an_adapter_reports_what_it_can_do(self):
        adapter = HikvisionAdapter()

        assert adapter.supports(Capability.SEARCH_RECORDINGS) is True
        assert adapter.supports(Capability.READ_LOGS) is False

    def test_requiring_an_unsupported_capability_explains_why(self):
        with pytest.raises(AdapterError) as raised:
            GodrejAdapter().require(Capability.DOWNLOAD_RECORDING)

        assert raised.value.code is ErrorCode.CAPABILITY_UNAVAILABLE
        assert "not a bug" in raised.value.detail

    def test_requiring_a_supported_capability_is_silent(self):
        assert HikvisionAdapter().require(Capability.IDENTIFY) is None


class TestEvidenceRecorder:
    def test_warnings_and_timing_are_collected(self):
        recorder = EvidenceRecorder(HikvisionAdapter.probe_method)
        recorder.warn("storage endpoint unavailable")

        evidence = recorder.finish()

        assert evidence.warnings == ["storage endpoint unavailable"]
        assert evidence.duration_ms >= 0
        assert evidence.finished_at >= evidence.started_at
        assert evidence.artifacts == []

    def test_a_client_contributes_its_artifacts_and_endpoints(
        self, hikvision_server, client_factory
    ):
        from models.common import ProbeMethod
        from tests.mock_dvr.hikvision import DEVICE_INFO

        client = client_factory(hikvision_server)
        client.get(DEVICE_INFO, ProbeMethod.HIKVISION_ISAPI)
        recorder = EvidenceRecorder(ProbeMethod.HIKVISION_ISAPI)

        evidence = recorder.finish(client)

        assert evidence.endpoints_attempted == [DEVICE_INFO]
        assert evidence.endpoints_succeeded == [DEVICE_INFO]
        assert len(evidence.artifacts) == 1


class TestRegistryShape:
    def test_badges_map_onto_the_lineage_they_actually_speak(self):
        """CP Plus is Dahua firmware; Godrej is XiongMai. The badge is not the stack."""
        assert VENDOR_FAMILY[Vendor.CPPLUS] is VendorFamily.DAHUA
        assert VENDOR_FAMILY[Vendor.GODREJ] is VendorFamily.XIONGMAI
        assert VENDOR_FAMILY[Vendor.UNKNOWN] is VendorFamily.UNKNOWN

    def test_every_adapter_declares_its_evidential_basis(self):
        for adapter in ADAPTERS:
            assert adapter.provenance, f"{adapter.vendor.value} has no stated provenance"
            assert adapter.capabilities

    def test_the_registry_description_matches_the_adapters(self):
        described = {entry["vendor"]: entry for entry in supported_vendors()}

        for adapter in ADAPTERS:
            entry = described[adapter.vendor.value]
            assert entry["family"] == adapter.family.value
            assert entry["capabilities"] == sorted(c.value for c in adapter.capabilities)
            assert entry["sdk_port"] == adapter.sdk_port

"""Vendor detection: which adapter claims the device, and on what evidence.

Detection decides which parser the rest of the pipeline uses, so a wrong answer
is not a cosmetic failure - it sends the whole acquisition down the wrong
protocol. These tests therefore assert the reported *signals* as well as the
verdict: a right answer for an unstated reason is not a forensic result.
"""

import re

import pytest

from models.common import Confidence, ErrorCode, ProbeMethod, Vendor, VendorFamily
from tests.conftest import make_client
from vendors.cpplus import CpPlusAdapter
from vendors.dahua import DahuaAdapter
from vendors.hikvision import HikvisionAdapter
from vendors.registry import (
    AMBIGUITY_MARGIN,
    CONFIDENT_SCORE,
    MINIMUM_SCORE,
    adapter_for,
    detect,
)
from vendors.transports.http_digest import TransportError


def test_hikvision_mock_is_detected_as_hikvision(hik_client):
    result = detect(hik_client)

    assert result.vendor is Vendor.HIKVISION
    assert result.family == VendorFamily.HIKVISION.value
    assert result.confidence == Confidence.CONFIRMED.value
    assert result.method is ProbeMethod.HIKVISION_ISAPI
    assert any("bare MAC" in signal for signal in result.signals)
    assert any("DeviceInfo document" in signal for signal in result.signals)
    assert result.candidates == ["HIKVISION=95"]


def test_dahua_mock_is_detected_as_dahua(dahua_client):
    result = detect(dahua_client)

    assert result.vendor is Vendor.DAHUA
    assert result.family == VendorFamily.DAHUA.value
    assert result.confidence == Confidence.CONFIRMED.value
    assert result.method is ProbeMethod.DAHUA_CGI
    assert any("DH_ prefix" in signal for signal in result.signals)
    assert any("magicBox.cgi" in signal for signal in result.signals)


def test_cpplus_branding_outscores_plain_dahua(cpplus_client):
    """CP Plus is Dahua firmware, so it must win on branding, not on protocol."""
    result = detect(cpplus_client)

    assert result.vendor is Vendor.CPPLUS
    assert result.family == VendorFamily.DAHUA.value
    scores = dict(pair.split("=") for pair in result.candidates)
    assert int(scores["CPPLUS"]) > int(scores["DAHUA"])
    assert any("CP Plus branding" in signal for signal in result.signals)


def test_cpplus_and_dahua_are_reported_as_ambiguous(cpplus_client):
    """A near-tie between two badges on one lineage is stated, not resolved."""
    result = detect(cpplus_client)

    assert result.confidence == Confidence.PROBABLE.value
    assert any(signal.startswith("ambiguous:") for signal in result.signals)


def test_unbranded_dahua_is_not_claimed_by_cpplus(dahua_client):
    """Absent CP Plus tokens, the CP Plus adapter must stand down."""
    dahua = DahuaAdapter.fingerprint(dahua_client)
    cpplus = CpPlusAdapter.fingerprint(dahua_client)

    assert dahua.score > cpplus.score
    assert any("no CP Plus branding" in signal for signal in cpplus.signals)


def test_unrecognised_device_yields_unknown_vendor(blank_server, client_factory):
    """A reachable host that matches nothing is UNKNOWN, never a best guess."""
    client = client_factory(blank_server)

    result = detect(client)

    assert result.vendor is Vendor.UNKNOWN
    assert result.family == VendorFamily.UNKNOWN.value
    assert result.confidence == Confidence.UNKNOWN.value
    assert result.signals == ["no adapter recognised this device"]
    assert result.candidates == []


def test_scores_of_every_adapter_against_the_hikvision_mock(hik_client):
    """The Dahua family must not raise a single vendor signal on an ISAPI device."""
    hikvision = HikvisionAdapter.fingerprint(hik_client)
    dahua = DahuaAdapter.fingerprint(hik_client)

    assert hikvision.score >= CONFIDENT_SCORE
    assert hikvision.score - dahua.score > AMBIGUITY_MARGIN
    assert not any("DH_ prefix" in signal for signal in dahua.signals)
    assert not any("system-info key/value" in signal for signal in dahua.signals)


def test_realm_shape_alone_separates_the_two_families(hikvision_server, dahua_server):
    """The digest realm identifies the family before a credential is offered."""
    with make_client(hikvision_server) as hik, make_client(dahua_server) as dahua:
        hik_realm = hik.challenge().realm
        dahua_realm = dahua.challenge().realm

        assert re.fullmatch(r"[0-9A-Fa-f]{12}", hik_realm)
        assert dahua_realm.startswith("DH_")
        assert not re.fullmatch(r"[0-9A-Fa-f]{12}", dahua_realm)

        # Both realms still yield the same MAC once the prefix is stripped.
        assert hik.challenge().realm_mac == "4419b66d2485"
        assert dahua.challenge().realm_mac == "00408CA5EA04"


def test_blank_device_has_no_realm_to_fingerprint(blank_server, client_factory):
    challenge = client_factory(blank_server).challenge()

    assert challenge.scheme is None
    assert challenge.realm is None
    assert challenge.realm_mac is None


def test_operator_hint_that_the_device_contradicts_is_recorded_and_ignored(hik_client):
    """An operator's assertion never overrides what the wire says."""
    result = detect(hik_client, vendor_hint=Vendor.GODREJ)

    assert result.vendor is Vendor.HIKVISION
    assert any("contradicted by the device" in signal for signal in result.signals)


def test_plausible_but_losing_hint_is_reported_as_such(cpplus_client):
    """DAHUA is a defensible hint for a CP Plus box; say so and move on."""
    result = detect(cpplus_client, vendor_hint=Vendor.DAHUA)

    assert result.vendor is Vendor.CPPLUS
    assert any("is plausible" in signal for signal in result.signals)


def test_a_guarded_recorder_is_fingerprinted_without_credentials(
    hikvision_server, client_factory
):
    """Detection has to work before anyone has the password.

    A 401 on a vendor-specific path is itself evidence: the path is served and
    guarded. Failing the whole probe instead would make an investigator guess
    the vendor before they could ask for credentials.
    """
    anonymous = client_factory(hikvision_server, username=None, password=None)

    result = detect(anonymous)

    assert result.vendor is Vendor.HIKVISION
    assert any("bare MAC" in signal for signal in result.signals)
    assert any("requires authentication" in signal for signal in result.signals)


def test_an_unauthenticated_fingerprint_still_names_the_dahua_family(
    dahua_server, client_factory
):
    """The DH_ realm alone is enough to place the device in its lineage."""
    anonymous = client_factory(dahua_server, username=None, password=None)

    result = detect(anonymous)

    assert result.vendor is Vendor.DAHUA
    assert result.family == VendorFamily.DAHUA.value
    assert any("DH_ prefix" in signal for signal in result.signals)


def test_wrong_credentials_do_not_abort_detection_of_the_other_adapters(
    hikvision_server, client_factory, monkeypatch
):
    """One adapter's rejection is a signal about that adapter, not a dead end."""

    def refuse(cls, client):
        raise TransportError(ErrorCode.AUTH_FAILED, "rejected", "HTTP 401")

    monkeypatch.setattr(DahuaAdapter, "fingerprint", classmethod(refuse))
    client = client_factory(hikvision_server)

    result = detect(client)

    assert result.vendor is Vendor.HIKVISION
    assert "DAHUA=30" in result.candidates


def test_an_unreachable_host_still_aborts_detection(closed_port):
    """Nothing is learned by asking four adapters about a host that is not there."""
    from vendors.transports.http_digest import HttpDeviceClient

    with HttpDeviceClient("127.0.0.1", closed_port, "admin", "x", timeout=2) as client:
        with pytest.raises(TransportError) as raised:
            detect(client)

    assert raised.value.code is ErrorCode.UNREACHABLE


class TestConfidenceCeiling:
    """No score may promote a vendor past what its own adapter can support."""

    def test_a_fingerprint_derived_vendor_is_capped_at_probable(
        self, blank_server, client_factory, dvrip_server
    ):
        client = client_factory(blank_server, sdk_port=dvrip_server.port)

        result = detect(client)

        assert result.vendor is Vendor.GODREJ
        # 85 would otherwise clear the CONFIRMED threshold outright.
        assert result.candidates == ["GODREJ=85"]
        assert result.confidence == Confidence.PROBABLE.value
        assert any("capped at PROBABLE" in signal for signal in result.signals)

    def test_the_cap_names_the_reason_it_applies(
        self, blank_server, client_factory, dvrip_server
    ):
        client = client_factory(blank_server, sdk_port=dvrip_server.port)

        result = detect(client)

        capped = next(signal for signal in result.signals if "capped" in signal)
        assert "fingerprint-derived, not vendor-published" in capped

    def test_cpplus_is_capped_too(self, cpplus_client):
        result = detect(cpplus_client)

        assert result.vendor is Vendor.CPPLUS
        assert result.confidence == Confidence.PROBABLE.value
        assert any("capped at PROBABLE" in signal for signal in result.signals)

    def test_a_vendor_published_protocol_is_not_capped(self, hik_client):
        """Hikvision documents ISAPI, so a strong fingerprint may say CONFIRMED."""
        result = detect(hik_client)

        assert result.confidence == Confidence.CONFIRMED.value
        assert not any("capped" in signal for signal in result.signals)

    def test_every_adapter_declares_a_ceiling(self):
        for adapter in (HikvisionAdapter, DahuaAdapter, CpPlusAdapter):
            assert adapter.max_confidence in (Confidence.CONFIRMED, Confidence.PROBABLE)

    def test_the_ceiling_matches_the_confidence_the_adapter_itself_reports(
        self, cpplus_client
    ):
        """A capped detection and the adapter's own identification must agree."""
        device = CpPlusAdapter().identify(cpplus_client)

        assert device.identity.confidence is CpPlusAdapter.max_confidence


def test_adapter_for_returns_the_registered_implementation():
    assert isinstance(adapter_for(Vendor.HIKVISION), HikvisionAdapter)
    assert isinstance(adapter_for(Vendor.CPPLUS), CpPlusAdapter)
    # CP Plus inherits the Dahua CGI implementation rather than duplicating it.
    assert isinstance(adapter_for(Vendor.CPPLUS), DahuaAdapter)


def test_adapter_for_an_unregistered_vendor_raises():
    with pytest.raises(KeyError):
        adapter_for(Vendor.UNKNOWN)

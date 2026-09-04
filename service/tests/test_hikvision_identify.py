"""Hikvision identification: the standardized object and its provenance.

The adapter contract is that normalization must not destroy provenance, so
these tests check both halves - the normalized view *and* the verbatim payload
plus its hash - rather than trusting that a populated field came from the wire.
"""

import hashlib
from datetime import datetime, timezone

import pytest

from models.common import Capability, Confidence, DeviceKind, ProbeMethod, Vendor
from tests.mock_dvr import hikvision as mock
from vendors.hikvision import HikvisionAdapter, as_list, parse_isapi_time, parse_isapi_xml

#: 1907729 MB expressed in bytes. Recomputed here from the constant rather than
#: copied from a report, because a wrong conversion is a wrong storage figure
#: in evidence: 1907729 * 1024 * 1024.
EXPECTED_CAPACITY_BYTES = 2000398843904
EXPECTED_FREE_BYTES = 107374182400


@pytest.fixture
def device(hik_client):
    return HikvisionAdapter().identify(hik_client)


def test_identity_fields_come_from_the_device_info_document(device):
    identity = device.identity

    assert identity.vendor is Vendor.HIKVISION
    assert identity.confidence is Confidence.CONFIRMED
    assert identity.kind is DeviceKind.DVR
    assert identity.model_name == mock.MODEL
    assert identity.serial_number == mock.SERIAL_NUMBER
    assert identity.firmware_version == mock.FIRMWARE_VERSION
    assert identity.firmware_released == mock.FIRMWARE_RELEASED
    assert identity.hardware_version == mock.HARDWARE_VERSION
    assert identity.mac_address == mock.MAC_ADDRESS
    assert identity.device_name == mock.DEVICE_NAME


def test_an_nvr_is_not_reported_as_a_dvr(hikvision_nvr_server, client_factory):
    """deviceType drives the kind; the same firmware ships in both roles."""
    client = client_factory(hikvision_nvr_server)

    device = HikvisionAdapter().identify(client)

    assert device.identity.kind is DeviceKind.NVR


def test_network_block_records_the_ports_actually_used(device, hikvision_server):
    assert device.network.host == hikvision_server.host
    assert device.network.http_port == hikvision_server.port
    assert device.network.https_port is None
    assert device.network.rtsp_port == 554
    # Hikvision's private SDK port, recorded even though ISAPI is what we speak.
    assert device.network.sdk_port == 8000


def test_analog_and_ip_channels_are_enumerated_and_distinguished(device):
    assert len(device.channels) == 6
    assert device.analog_channel_count == 4
    assert device.digital_channel_count == 2

    first = device.channels[0]
    assert first.channel_id == "1"
    assert first.name == "Front Gate"
    assert first.enabled is True
    assert first.resolution == "1920*1080P"
    # Hikvision track IDs are channel*100 + stream, so ch1 main is 101.
    assert first.track_id == "101"
    assert [c.track_id for c in device.channels] == [
        "101",
        "201",
        "301",
        "401",
        "3301",
        "3401",
    ]


def test_storage_capacity_is_converted_from_megabytes(device):
    """ISAPI reports MB; evidence figures must be bytes or they mean nothing."""
    assert len(device.storage) == 1
    disk = device.storage[0]

    assert disk.storage_id == "1"
    assert disk.name == "hde1"
    assert disk.kind == "SATA"
    assert disk.status == "ok"
    assert disk.device_property == "RW"
    assert disk.capacity_bytes == EXPECTED_CAPACITY_BYTES
    assert disk.free_bytes == EXPECTED_FREE_BYTES
    assert disk.capacity_bytes == mock.HDD_CAPACITY_MB * 1024 * 1024
    assert disk.used_bytes == EXPECTED_CAPACITY_BYTES - EXPECTED_FREE_BYTES
    assert device.total_capacity_bytes == EXPECTED_CAPACITY_BYTES


def test_single_disk_list_is_not_collapsed_into_nothing(device):
    """xmltodict returns a bare dict for a one-element list; as_list fixes it."""
    hdd_list = device.raw["/ISAPI/ContentMgmt/Storage/hdd"]["hddList"]

    assert isinstance(hdd_list["hdd"], dict)  # the collapsed shape
    assert len(as_list(hdd_list["hdd"])) == 1
    assert len(device.storage) == 1


def test_clock_is_read_with_timezone_and_ntp_state(device):
    clock = device.clock

    assert clock.device_time_raw == mock.DEVICE_TIME
    assert clock.device_time == datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
    assert clock.timezone == "CST-5:30:00"
    assert clock.ntp_enabled is True
    assert clock.ntp_servers == ["pool.ntp.org"]
    assert clock.probed_at is not None


def test_drift_is_recorder_time_minus_host_time(device):
    """Drift is the offset every later timeline claim is corrected by."""
    clock = device.clock

    assert clock.drift_seconds is not None
    expected = (clock.device_time - clock.probed_at).total_seconds()
    assert clock.drift_seconds == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("offset", [125.0, -240.0])
def test_drift_matches_a_known_recorder_offset(
    hikvision_server, client_factory, offset
):
    """With the recorder's clock pinned to host+offset, drift must be offset.

    Tolerance covers the round trip between the mock formatting its clock and
    the adapter stamping probed_at, plus the one-second resolution of the ISAPI
    timestamp format.
    """
    hikvision_server.clock_offset_seconds = offset
    client = client_factory(hikvision_server)

    device = HikvisionAdapter().identify(client)

    assert device.clock.drift_seconds == pytest.approx(offset, abs=2.0)


def test_capabilities_are_declared_honestly(device):
    assert Capability.SEARCH_RECORDINGS in device.capabilities
    assert Capability.DOWNLOAD_RECORDING in device.capabilities
    assert Capability.READ_LOGS not in device.capabilities
    assert Capability.READ_USERS not in device.capabilities


def test_raw_payloads_are_retained_for_every_endpoint(device):
    assert set(device.raw) == {
        "/ISAPI/System/deviceInfo",
        "/ISAPI/System/Video/inputs/channels",
        "/ISAPI/ContentMgmt/InputProxy/channels",
        "/ISAPI/ContentMgmt/Storage/hdd",
        "/ISAPI/System/time",
        "/ISAPI/System/time/ntpServers",
    }
    # The verbatim vendor field names survive normalization.
    assert device.raw["/ISAPI/System/deviceInfo"]["serialNumber"] == mock.SERIAL_NUMBER


def test_every_artifact_hash_covers_its_own_body(device):
    assert device.evidence.artifacts

    for artifact in device.evidence.artifacts:
        assert artifact.method is ProbeMethod.HIKVISION_ISAPI
        assert artifact.status_code == 200
        assert artifact.sha256 == hashlib.sha256(artifact.body.encode("utf-8")).hexdigest()
        assert artifact.retrieved_at.tzinfo is not None


def test_evidence_records_which_endpoints_answered(device):
    assert "/ISAPI/System/deviceInfo" in device.evidence.endpoints_attempted
    assert "/ISAPI/System/deviceInfo" in device.evidence.endpoints_succeeded
    assert device.evidence.duration_ms >= 0
    assert device.evidence.finished_at >= device.evidence.started_at


def test_missing_optional_endpoints_are_warned_about_not_hidden(
    hikvision_server, client_factory
):
    """A firmware without InputProxy is a gap in the record, not a failure."""
    hikvision_server.disabled_paths = {"/ISAPI/ContentMgmt/InputProxy/channels"}
    client = client_factory(hikvision_server)

    device = HikvisionAdapter().identify(client)

    assert device.analog_channel_count == 4
    assert device.digital_channel_count == 0
    assert any("InputProxy" in warning for warning in device.evidence.warnings)


def test_a_recorder_without_a_clock_endpoint_says_so(hikvision_server, client_factory):
    """An unmeasured clock must be visible, not silently reported as zero drift."""
    hikvision_server.disabled_paths = {"/ISAPI/System/time"}
    client = client_factory(hikvision_server)

    device = HikvisionAdapter().identify(client)

    assert device.clock.drift_seconds is None
    assert any("clock drift" in warning for warning in device.evidence.warnings)


def test_a_host_that_does_not_speak_isapi_is_rejected_not_guessed(
    blank_server, client_factory
):
    """Answering HTTP is not the same as being a Hikvision recorder."""
    from vendors.base import AdapterError

    client = client_factory(blank_server)

    with pytest.raises(AdapterError) as raised:
        HikvisionAdapter().identify(client)

    assert raised.value.code.value == "PROTOCOL_ERROR"


def test_parse_isapi_time_handles_both_isapi_formats():
    compact = parse_isapi_time("20260904T080000Z")
    extended = parse_isapi_time("2026-09-04T08:00:00Z")

    assert compact == extended == datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    assert parse_isapi_time(None) is None
    assert parse_isapi_time("not a time") is None


def test_namespaces_are_stripped_but_content_is_not():
    document = parse_isapi_xml(
        '<?xml version="1.0"?><DeviceInfo xmlns="http://x/ver20/XMLSchema">'
        "<model>DS-1</model></DeviceInfo>"
    )

    assert document == {"DeviceInfo": {"model": "DS-1"}}
    assert parse_isapi_xml("") == {}

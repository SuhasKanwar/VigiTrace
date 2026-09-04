"""Dahua and CP Plus identification over the HTTP CGI surface.

Dahua encodes structure in the key rather than the body, so most of the risk
here is in the flat-key parser: an index or a dotted path parsed wrongly turns
a disk into nothing at all.
"""

import pytest

from models.common import Confidence, DeviceKind, Vendor, VendorFamily
from tests.mock_dvr import dahua as mock
from vendors.cpplus import CpPlusAdapter
from vendors.dahua import DahuaAdapter, parse_dahua_time, parse_kv

EXPECTED_CAPACITY_BYTES = 2000398843904  # 1907729 MB
EXPECTED_FREE_BYTES = 107374182400  # (1907729 - 1805329) MB


@pytest.fixture
def device(dahua_client):
    return DahuaAdapter().identify(dahua_client)


def test_identity_is_assembled_from_several_cgi_actions(device):
    identity = device.identity

    assert identity.vendor is Vendor.DAHUA
    assert identity.family is VendorFamily.DAHUA
    assert identity.confidence is Confidence.CONFIRMED
    assert identity.kind is DeviceKind.NVR
    assert identity.model_name == mock.DEVICE_TYPE
    assert identity.serial_number == mock.SERIAL_NUMBER
    assert identity.firmware_version == mock.SOFTWARE_VERSION
    assert identity.hardware_version == mock.HARDWARE_VERSION
    assert identity.device_name == mock.MACHINE_NAME


def test_mac_is_recovered_from_the_digest_realm(device):
    """The CGI never reports the MAC, but the DH_ realm carries it."""
    assert device.identity.mac_address == "00:40:8c:a5:ea:04"
    assert device.network.mac_address == "00:40:8c:a5:ea:04"


def test_serial_falls_back_to_the_other_action_that_reports_it(
    dahua_server, client_factory
):
    """getSystemInfo and getSerialNo disagree on the key for the same value."""
    dahua_server.serial_in_system_info = False
    client = client_factory(dahua_server)

    device = DahuaAdapter().identify(client)

    assert device.identity.serial_number == mock.SERIAL_NUMBER
    assert device.raw["magicBox.getSerialNo"] == {"sn": mock.SERIAL_NUMBER}


def test_channels_are_enumerated_from_the_indexed_key_format(device):
    assert len(device.channels) == 4
    assert [c.channel_id for c in device.channels] == ["1", "2", "3", "4"]
    assert device.channels[0].name == "Front Gate"
    # The CGI does not say whether an input is analog, so the adapter must not
    # invent an answer.
    assert all(c.is_analog is None for c in device.channels)
    assert device.analog_channel_count == 0


def test_storage_totals_are_converted_from_megabytes(device):
    assert len(device.storage) == 1
    disk = device.storage[0]

    assert disk.storage_id == "/dev/sda0"
    assert disk.name == "/dev/sda0"
    assert disk.status == "Running"
    assert disk.kind == "Read/Write"
    assert disk.capacity_bytes == EXPECTED_CAPACITY_BYTES
    assert disk.capacity_bytes == mock.STORAGE_TOTAL_MB * 1024 * 1024
    # Dahua reports used, not free; free is the difference.
    assert disk.free_bytes == EXPECTED_FREE_BYTES
    assert disk.free_bytes == (mock.STORAGE_TOTAL_MB - mock.STORAGE_USED_MB) * 1024 * 1024
    assert disk.used_bytes == mock.STORAGE_USED_MB * 1024 * 1024


def test_clock_and_ntp_configuration_are_read(device):
    clock = device.clock

    assert clock.device_time_raw == mock.DEVICE_TIME
    assert clock.device_time.isoformat() == "2026-09-04T10:00:00+00:00"
    assert clock.ntp_enabled is True
    assert clock.ntp_servers == ["clock.isc.org"]
    assert clock.timezone == "5"
    assert clock.drift_seconds is not None


@pytest.mark.parametrize("offset", [90.0, -300.0])
def test_drift_matches_a_known_recorder_offset(dahua_server, client_factory, offset):
    dahua_server.clock_offset_seconds = offset
    client = client_factory(dahua_server)

    device = DahuaAdapter().identify(client)

    assert device.clock.drift_seconds == pytest.approx(offset, abs=2.0)


def test_raw_payloads_are_kept_per_cgi_action(device):
    assert set(device.raw) == {
        "magicBox.getSystemInfo",
        "magicBox.getSoftwareVersion",
        "magicBox.getMachineName",
        "devVideoInput.getCollect",
        "storageDevice.getDeviceAllInfo",
        "global.getCurrentTime",
        "configManager.NTP",
    }
    assert device.raw["magicBox.getSystemInfo"]["serialNumber"] == mock.SERIAL_NUMBER
    assert device.raw["configManager.NTP"]["table"]["NTP"]["Address"] == "clock.isc.org"


def test_a_host_that_does_not_speak_the_cgi_api_is_rejected(blank_server, client_factory):
    from vendors.base import AdapterError

    client = client_factory(blank_server)

    with pytest.raises(AdapterError) as raised:
        DahuaAdapter().identify(client)

    assert raised.value.code.value == "PROTOCOL_ERROR"


class TestCpPlus:
    """CP Plus is Dahua firmware; only branding and confidence differ."""

    @pytest.fixture
    def device(self, cpplus_client):
        return CpPlusAdapter().identify(cpplus_client)

    def test_vendor_is_rebadged_but_the_family_stays_dahua(self, device):
        assert device.identity.vendor is Vendor.CPPLUS
        assert device.identity.family is VendorFamily.DAHUA

    def test_attribution_never_rises_above_probable(self, device):
        """The lineage is inferred from artifacts, not published by CP Plus."""
        assert device.identity.confidence is Confidence.PROBABLE
        assert any(
            "Dahua firmware lineage" in warning for warning in device.evidence.warnings
        )

    def test_dahua_field_extraction_still_applies(self, device):
        assert device.identity.serial_number == mock.SERIAL_NUMBER
        assert device.identity.firmware_version == mock.CPPLUS_SOFTWARE_VERSION
        assert len(device.channels) == 4
        assert device.storage[0].capacity_bytes == EXPECTED_CAPACITY_BYTES

    def test_cpplus_model_naming_is_classified(self, device):
        """CP Plus names its recorders UNR/UVR, not NVR/DVR.

        The device kind drives what an investigator expects to find - IP
        streams or analog channels - so an OEM prefix must not leave it
        UNKNOWN.
        """
        assert device.identity.model_name == mock.CPPLUS_DEVICE_TYPE
        assert device.identity.kind is DeviceKind.NVR


class TestFlatKeyParser:
    """parse_kv turns Dahua's key-encoded structure into real containers."""

    def test_dotted_paths_become_nested_dicts(self):
        assert parse_kv("table.NTP.Address=clock.isc.org\r\n") == {
            "table": {"NTP": {"Address": "clock.isc.org"}}
        }

    def test_indexed_keys_become_lists(self):
        parsed = parse_kv("items[0].Channel=1\r\nitems[1].Channel=2\r\n")

        assert parsed == {"items": [{"Channel": "1"}, {"Channel": "2"}]}

    def test_sparse_indices_are_padded_not_dropped(self):
        """A skipped index must not shift the remaining entries up one slot."""
        parsed = parse_kv("list[2].Name=c\r\n")

        assert parsed["list"] == [{}, {}, {"Name": "c"}]

    def test_nested_indices_are_supported(self):
        parsed = parse_kv("list[0].Detail[0].TotalBytes=1907729\r\n")

        assert parsed["list"][0]["Detail"][0]["TotalBytes"] == "1907729"

    def test_lines_without_a_value_separator_are_ignored(self):
        assert parse_kv("OK\r\n") == {}
        assert parse_kv("") == {}

    def test_values_containing_equals_are_kept_whole(self):
        assert parse_kv("version=2.212=R\r\n") == {"version": "2.212=R"}


@pytest.mark.parametrize(
    "device_type, expected",
    [
        ("NVR4216", DeviceKind.NVR),
        ("XVR5108HS-X", DeviceKind.XVR),
        ("HCVR7208A-S3", DeviceKind.HVR),
        ("DHI-DVR5104HS", DeviceKind.DVR),
        ("IPC-HDW1230T", DeviceKind.IPC),
        # CP Plus rebadges: UNR for network recorders, UVR/UAR for analog.
        ("CP-UNR-4K4162-V2", DeviceKind.NVR),
        ("CP-UVR-0401E1-CS", DeviceKind.DVR),
        ("CP-UAR-0401F1-HC", DeviceKind.DVR),
        ("something else", DeviceKind.UNKNOWN),
        (None, DeviceKind.UNKNOWN),
    ],
)
def test_device_kind_is_derived_from_the_model_string(device_type, expected):
    """An HCVR is a hybrid, not a DVR, even though the token contains one."""
    assert DahuaAdapter._kind_from_type(device_type) is expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-09-04 10:00:00", "2026-09-04T10:00:00+00:00"),
        ("2026-09-04 10-00-00", "2026-09-04T10:00:00+00:00"),
        ("2026-09-04T10:00:00", "2026-09-04T10:00:00+00:00"),
    ],
)
def test_dahua_timestamp_formats(value, expected):
    assert parse_dahua_time(value).isoformat() == expected


def test_unparsable_dahua_timestamps_return_none():
    assert parse_dahua_time("yesterday") is None
    assert parse_dahua_time(None) is None

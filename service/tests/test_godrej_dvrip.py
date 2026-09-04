"""Godrej / XiongMai DVRIP: a binary protocol with no HTTP surface at all.

The adapter is handed an HTTP client like every other adapter and has to open
its own TCP session. The port for that session comes from the client's
``sdk_port``, which is how these tests reach the mock on its ephemeral port and
how an operator reaches a recorder whose DVRIP port has been moved.
"""

import socket
from datetime import datetime, timezone

import pytest

from models.common import Capability, Confidence, DeviceKind, ProbeMethod, Vendor, VendorFamily
from tests.mock_dvr import dvrip as mock
from vendors.base import AdapterError
from vendors.godrej import GodrejAdapter
from vendors.registry import detect
from vendors.transports.dvrip import DEFAULT_PORT, DvripClient, port_open, sofia_hash
from vendors.transports.http_digest import TransportError

EXPECTED_CAPACITY_BYTES = mock.TOTAL_SPACE_MB * 1024 * 1024
EXPECTED_FREE_BYTES = mock.REMAIN_SPACE_MB * 1024 * 1024


@pytest.fixture
def dvrip_port(dvrip_server):
    """The ephemeral port the DVRIP mock is listening on."""
    return dvrip_server.port


@pytest.fixture
def godrej_client(blank_server, client_factory, dvrip_port):
    """A XiongMai box: a web UI that fingerprints as nothing, plus DVRIP."""
    return client_factory(blank_server, sdk_port=dvrip_port)


@pytest.fixture
def device(godrej_client):
    return GodrejAdapter().identify(godrej_client)


class TestSofiaHash:
    """The password digest is required to speak the protocol at all."""

    def test_empty_password_matches_the_known_value(self):
        assert sofia_hash("") == "tlJwpbo6"

    def test_digest_is_eight_characters_from_the_vendor_alphabet(self):
        alphabet = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")

        for password in ("admin", "Vigi#Trace1", "x" * 64):
            digest = sofia_hash(password)
            assert len(digest) == 8
            assert set(digest) <= alphabet

    def test_the_client_sends_the_digest_not_the_password(self, dvrip_server):
        with DvripClient(
            dvrip_server.host, dvrip_server.port, "admin", "Vigi#Trace1", timeout=5
        ) as session:
            session.login()

        assert dvrip_server.passwords_seen == [sofia_hash("Vigi#Trace1")]
        assert "Vigi#Trace1" not in dvrip_server.passwords_seen


class TestPortProbe:
    def test_an_open_dvrip_port_is_detected(self, dvrip_server):
        assert port_open(dvrip_server.host, dvrip_server.port, timeout=2.0) is True

    def test_a_closed_port_is_not(self, closed_port):
        assert port_open("127.0.0.1", closed_port, timeout=2.0) is False


class TestFingerprint:
    def test_an_answering_dvrip_service_identifies_the_family(
        self, godrej_client, dvrip_port
    ):
        result = GodrejAdapter.fingerprint(godrej_client)

        assert result.vendor is Vendor.GODREJ
        assert result.score == 85
        assert any("DVRIP" in signal and "open" in signal for signal in result.signals)
        assert any("login handshake accepted" in signal for signal in result.signals)

    def test_wrong_credentials_still_confirm_the_protocol_family(
        self, blank_server, client_factory, dvrip_port
    ):
        """Speaking DVRIP is the vendor signal; the password is not."""
        client = client_factory(blank_server, password="wrong", sdk_port=dvrip_port)

        result = GodrejAdapter.fingerprint(client)

        assert result.score == 75
        assert any("answered the login handshake" in signal for signal in result.signals)

    def test_no_dvrip_service_means_no_signal(self, blank_server, client_factory, closed_port):
        client = client_factory(blank_server, sdk_port=closed_port)

        result = GodrejAdapter.fingerprint(client)

        assert result.score == 0
        assert result.signals == []

    def test_detection_picks_godrej_when_only_dvrip_answers(
        self, godrej_client, dvrip_port
    ):
        result = detect(godrej_client)

        assert result.vendor is Vendor.GODREJ
        assert result.family == VendorFamily.XIONGMAI.value
        assert result.method is ProbeMethod.XIONGMAI_DVRIP
        assert result.candidates == ["GODREJ=85"]


class TestIdentify:
    def test_identity_comes_from_the_systeminfo_block(self, device):
        identity = device.identity

        assert identity.vendor is Vendor.GODREJ
        assert identity.family is VendorFamily.XIONGMAI
        assert identity.kind is DeviceKind.DVR
        assert identity.model_name == mock.HARDWARE
        assert identity.serial_number == mock.SERIAL_NO
        assert identity.firmware_version == mock.SOFTWARE_VERSION
        assert identity.firmware_released == mock.BUILD_TIME

    def test_attribution_is_never_better_than_probable(self, device):
        """Godrej publishes no protocol documentation; nothing confirms this."""
        assert identity_confidence(device) is Confidence.PROBABLE
        assert any(
            "inferred from device fingerprints" in warning
            for warning in device.evidence.warnings
        )

    def test_channel_counts_are_expanded_into_records(self, device):
        assert len(device.channels) == mock.VIDEO_IN_CHANNELS
        assert device.analog_channel_count == mock.VIDEO_IN_CHANNELS
        assert device.digital_channel_count == 0
        assert [c.channel_id for c in device.channels] == ["1", "2", "3", "4"]
        # DVRIP reports counts only, so there is no per-channel name to record.
        assert all(c.name is None for c in device.channels)

    def test_the_dvrip_port_is_recorded_as_the_sdk_port(self, device, dvrip_port):
        assert device.network.sdk_port == dvrip_port
        assert device.network.rtsp_port == 554

    def test_clock_is_read_over_dvrip(self, device):
        assert device.clock.device_time_raw == mock.DEVICE_TIME
        assert device.clock.device_time == datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
        assert device.clock.drift_seconds is not None

    def test_drift_matches_a_known_recorder_offset(self, dvrip_server, godrej_client):
        offset = 45.0
        moment = datetime.now(timezone.utc).timestamp() + offset
        dvrip_server.device_time = datetime.fromtimestamp(moment, timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        device = GodrejAdapter().identify(godrej_client)

        assert device.clock.drift_seconds == pytest.approx(offset, abs=2.0)

    def test_capabilities_stop_short_of_recording_search(self, device):
        """DVRIP recording search is not implemented, and says so."""
        assert Capability.IDENTIFY in device.capabilities
        assert Capability.SEARCH_RECORDINGS not in device.capabilities
        assert Capability.DOWNLOAD_RECORDING not in device.capabilities

    def test_raw_dvrip_blocks_are_retained(self, device):
        assert set(device.raw) == {
            "dvrip.SystemInfo",
            "dvrip.StorageInfo",
            "dvrip.OPTimeQuery",
        }
        assert device.raw["dvrip.SystemInfo"]["SystemInfo"]["SerialNo"] == mock.SERIAL_NO

    def test_every_dvrip_exchange_is_kept_as_an_artifact(self, device):
        """Login, both info blocks and the clock query all reach the record."""
        artifacts = device.evidence.artifacts
        endpoints = [a.endpoint for a in artifacts]

        assert len(artifacts) == 4
        assert all(endpoint.startswith("dvrip:") for endpoint in endpoints)
        assert endpoints[0].startswith("dvrip:1000")
        assert endpoints[-1].startswith("dvrip:1452")
        assert all(a.method is ProbeMethod.XIONGMAI_DVRIP for a in artifacts)
        # Four distinct exchanges, so four distinct retained payloads.
        assert len({a.sha256 for a in artifacts}) == 4

    def test_bad_credentials_fail_the_login_handshake(
        self, blank_server, client_factory, dvrip_port
    ):
        client = client_factory(blank_server, password="wrong", sdk_port=dvrip_port)

        with pytest.raises(TransportError) as raised:
            GodrejAdapter().identify(client)

        assert raised.value.code.value == "AUTH_FAILED"

    def test_a_device_without_systeminfo_is_reported_as_unsupported(
        self, blank_server, client_factory, dvrip_server, monkeypatch
    ):
        """Godrej ships several generations; one that will not answer is news."""
        monkeypatch.setattr(
            dvrip_server,
            "_get_info",
            lambda request: {"Name": request.get("Name"), "Ret": 404},
        )
        client = client_factory(blank_server, sdk_port=dvrip_server.port)

        with pytest.raises(AdapterError) as raised:
            GodrejAdapter().identify(client)

        assert raised.value.code.value == "PROTOCOL_ERROR"


class TestStorage:
    def test_decimal_partition_sizes_are_converted_from_megabytes(
        self, dvrip_server, godrej_client
    ):
        dvrip_server.hex_space = False

        device = GodrejAdapter().identify(godrej_client)

        assert len(device.storage) == 1
        assert device.storage[0].capacity_bytes == EXPECTED_CAPACITY_BYTES
        assert device.storage[0].free_bytes == EXPECTED_FREE_BYTES
        assert device.storage[0].status == "Read&Write"

    def test_hex_partition_sizes_are_converted_from_megabytes(self, device):
        """XiongMai reports storage in hex, and the figure has to survive.

        Retention and overwrite pressure are judged from capacity and free
        space, so a dropped figure would silently remove the disk from that
        assessment.
        """
        disk = device.storage[0]

        assert device.raw["dvrip.StorageInfo"]["StorageInfo"][0][0]["Partition"][0][
            "TotalSpace"
        ] == mock.TOTAL_SPACE_HEX
        assert disk.capacity_bytes == EXPECTED_CAPACITY_BYTES
        assert disk.free_bytes == EXPECTED_FREE_BYTES

    def test_hex_and_decimal_firmware_report_the_same_disk(
        self, dvrip_server, blank_server, client_factory, dvrip_port
    ):
        """The encoding is a firmware detail; the recorded capacity must not vary."""
        hex_device = GodrejAdapter().identify(
            client_factory(blank_server, sdk_port=dvrip_port)
        )
        dvrip_server.hex_space = False
        decimal_device = GodrejAdapter().identify(
            client_factory(blank_server, sdk_port=dvrip_port)
        )

        assert hex_device.storage[0].capacity_bytes == decimal_device.storage[0].capacity_bytes
        assert hex_device.storage[0].free_bytes == decimal_device.storage[0].free_bytes

    def test_space_reported_at_two_levels_is_counted_once(
        self, dvrip_server, godrej_client
    ):
        """Firmware repeats the figure at disk and partition level.

        Counting both would double the reported capacity of a recorder, which
        would then read as twice the retention it actually has.
        """
        dvrip_server.hex_space = False
        dvrip_server.duplicate_disk_level_space = True

        device = GodrejAdapter().identify(godrej_client)

        assert len(device.storage) == 1
        assert device.total_capacity_bytes == EXPECTED_CAPACITY_BYTES
        # The partition record is the one kept, since it is the finer grain.
        assert device.storage[0].storage_id == "4a2b1c9d"

    def test_a_disk_reporting_space_only_at_the_top_level_is_still_recorded(
        self, dvrip_server, blank_server, client_factory, dvrip_port
    ):
        """Deduplication must not discard firmware that has no Partition block."""
        dvrip_server.hex_space = False
        dvrip_server.partitionless_disk = True

        device = GodrejAdapter().identify(client_factory(blank_server, sdk_port=dvrip_port))

        assert len(device.storage) == 1
        assert device.storage[0].capacity_bytes == EXPECTED_CAPACITY_BYTES


class TestTransportFraming:
    def test_a_non_dvrip_response_is_rejected(self, dvrip_server):
        dvrip_server.corrupt_magic = True

        with DvripClient(
            dvrip_server.host, dvrip_server.port, "admin", "Vigi#Trace1", timeout=5
        ) as session:
            with pytest.raises(TransportError) as raised:
                session.login()

        assert raised.value.code.value == "PROTOCOL_ERROR"
        assert "DVRIP frame header" in raised.value.message

    def test_an_implausible_payload_length_is_rejected(self, dvrip_server):
        dvrip_server.oversized_length = True

        with DvripClient(
            dvrip_server.host, dvrip_server.port, "admin", "Vigi#Trace1", timeout=5
        ) as session:
            with pytest.raises(TransportError) as raised:
                session.login()

        assert raised.value.code.value == "PROTOCOL_ERROR"
        assert "implausible payload length" in raised.value.message

    def test_a_refused_connection_is_unreachable_not_a_protocol_error(self, closed_port):
        session = DvripClient("127.0.0.1", closed_port, "admin", "", timeout=2)

        with pytest.raises(TransportError) as raised:
            session.connect()

        assert raised.value.code.value == "UNREACHABLE"

    def test_sending_without_a_connection_is_an_internal_error(self):
        session = DvripClient("127.0.0.1", 1, "admin", "")

        with pytest.raises(TransportError) as raised:
            session.login()

        assert raised.value.code.value == "INTERNAL"

    def test_the_session_id_from_the_frame_header_is_reused(self, dvrip_server):
        """Later requests must quote the session the recorder handed out."""
        with DvripClient(
            dvrip_server.host, dvrip_server.port, "admin", "Vigi#Trace1", timeout=5
        ) as session:
            session.login()
            session.get_info("SystemInfo")

        assert session.session == mock.SESSION_ID
        _message_id, info_request = dvrip_server.messages[-1]
        assert info_request["SessionID"] == f"0x{mock.SESSION_ID:08X}"


def identity_confidence(device):
    return device.identity.confidence


def _real_dvrip_port_is_free() -> bool:
    """Whether TCP 34567 is genuinely unused on this host.

    The fallback test below is only meaningful if nothing answers there, and
    unrelated local software occupying the port should skip it rather than fail
    it.
    """
    probe = socket.socket()
    probe.settimeout(1.0)
    try:
        return probe.connect_ex(("127.0.0.1", 34567)) != 0
    finally:
        probe.close()


def test_the_dvrip_port_is_taken_from_the_client(dvrip_server, blank_server, client_factory):
    """A recorder whose DVRIP port has been moved is still reachable.

    Hard-coding 34567 would make any hardened installation - port moved, or
    forwarded through a jump host - undiagnosable from this service.
    """
    client = client_factory(blank_server, sdk_port=dvrip_server.port)

    device = GodrejAdapter().identify(client)

    assert dvrip_server.port != DEFAULT_PORT
    assert device.network.sdk_port == dvrip_server.port
    assert device.identity.serial_number == mock.SERIAL_NO


def test_the_port_reaches_the_adapter_through_a_device_target(
    dvrip_server, blank_server
):
    """End to end: the operator sets it on the target, the DVRIP session uses it."""
    from services.probe import identify_device
    from tests.conftest import make_target

    response = identify_device(make_target(blank_server, sdk_port=dvrip_server.port))

    assert response.success is True
    assert response.device.identity.vendor is Vendor.GODREJ
    assert response.device.network.sdk_port == dvrip_server.port


@pytest.mark.skipif(
    not _real_dvrip_port_is_free(), reason="something is listening on TCP 34567 on this host"
)
def test_without_an_override_the_family_default_port_is_used(blank_server, client_factory):
    """Absent an override the adapter falls back to the XiongMai default."""
    client = client_factory(blank_server)

    with pytest.raises(TransportError) as raised:
        GodrejAdapter().identify(client)

    assert raised.value.code.value == "UNREACHABLE"
    assert str(DEFAULT_PORT) in raised.value.message
    assert DEFAULT_PORT == 34567

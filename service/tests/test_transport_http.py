"""The shared HTTP transport: auth negotiation and artifact retention.

Two behaviours here are load-bearing for everything above them. The auth scheme
is read from the recorder's own challenge rather than assumed, and every
response is retained verbatim with its hash, because normalization is not
allowed to destroy provenance.
"""

import hashlib

import pytest

from models.common import ErrorCode, ProbeMethod
from tests.conftest import make_client
from tests.mock_dvr.dahua import MAGICBOX
from tests.mock_dvr.hikvision import DEVICE_INFO
from vendors.transports.http_digest import AuthChallenge, HttpDeviceClient, TransportError


class TestAuthNegotiation:
    def test_the_challenge_is_read_before_any_credential_is_offered(
        self, hikvision_server, client_factory
    ):
        client = client_factory(hikvision_server)

        challenge = client.challenge()

        assert challenge.scheme == "Digest"
        assert challenge.realm == hikvision_server.realm
        assert challenge.raw_header.startswith("Digest ")
        # The probe itself must not have carried credentials.
        assert "Authorization" not in (hikvision_server.requests[0].query or {})

    def test_the_challenge_is_cached_as_a_property_of_the_device(
        self, hikvision_server, client_factory
    ):
        client = client_factory(hikvision_server)

        first = client.challenge()
        second = client.challenge()

        assert first is second
        assert len(hikvision_server.calls_to("/")) == 1

    def test_a_basic_only_recorder_is_answered_with_basic(
        self, hikvision_server, client_factory
    ):
        """Assuming Digest against a Basic-only device would never authenticate."""
        hikvision_server.auth_scheme = "Basic"
        client = client_factory(hikvision_server)

        challenge = client.challenge()
        artifact = client.get(DEVICE_INFO, ProbeMethod.HIKVISION_ISAPI)

        assert challenge.scheme == "Basic"
        assert artifact.status_code == 200
        assert "<DeviceInfo" in artifact.body

    def test_an_unchallenged_device_yields_an_empty_challenge(
        self, blank_server, client_factory
    ):
        challenge = client_factory(blank_server).challenge()

        assert challenge.scheme is None
        assert challenge.realm is None

    @pytest.mark.parametrize(
        "realm, expected",
        [
            ("4419b66d2485", "4419b66d2485"),
            ("DH_00408CA5EA04", "00408CA5EA04"),
            ("dh_00408ca5ea04", "00408ca5ea04"),
            ("Login to ABC", None),
            ("", None),
            (None, None),
        ],
    )
    def test_the_mac_is_recovered_from_either_realm_convention(self, realm, expected):
        assert AuthChallenge("Digest", realm, None).realm_mac == expected


class TestArtifactRetention:
    def test_every_response_is_retained_with_its_hash(self, hikvision_server, client_factory):
        client = client_factory(hikvision_server)

        artifact = client.get(DEVICE_INFO, ProbeMethod.HIKVISION_ISAPI)

        assert artifact.endpoint == DEVICE_INFO
        assert artifact.method is ProbeMethod.HIKVISION_ISAPI
        assert artifact.status_code == 200
        assert artifact.content_type.startswith("application/xml")
        assert artifact.sha256 == hashlib.sha256(artifact.body.encode("utf-8")).hexdigest()
        assert client.artifacts == [artifact]

    def test_attempted_and_succeeded_endpoints_are_tracked_separately(
        self, hikvision_server, client_factory
    ):
        hikvision_server.disabled_paths = {"/ISAPI/System/time"}
        client = client_factory(hikvision_server)

        client.get(DEVICE_INFO, ProbeMethod.HIKVISION_ISAPI)
        client.try_get("/ISAPI/System/time", ProbeMethod.HIKVISION_ISAPI)

        assert client.attempted == [DEVICE_INFO, "/ISAPI/System/time"]
        assert client.succeeded == [DEVICE_INFO]

    def test_a_failed_optional_endpoint_is_still_retained_as_evidence(
        self, hikvision_server, client_factory
    ):
        """A 404 is a fact about the device and belongs in the record."""
        hikvision_server.disabled_paths = {"/ISAPI/System/time"}
        client = client_factory(hikvision_server)

        result = client.try_get("/ISAPI/System/time", ProbeMethod.HIKVISION_ISAPI)

        assert result is None
        assert [a.status_code for a in client.artifacts] == [404]

    def test_query_parameters_are_part_of_the_retained_endpoint_label(
        self, dahua_server, client_factory
    ):
        """The CGI action is what identifies a Dahua call, not the path.

        Every magicBox action shares one path, so a bare-path label would make
        the evidence record unable to say which action produced which payload.
        """
        client = client_factory(dahua_server)

        client.get(MAGICBOX, ProbeMethod.DAHUA_CGI, action="getSystemInfo")
        client.get(MAGICBOX, ProbeMethod.DAHUA_CGI, action="getSerialNo")

        endpoints = [a.endpoint for a in client.artifacts]
        assert endpoints == [
            f"{MAGICBOX}?action=getSystemInfo",
            f"{MAGICBOX}?action=getSerialNo",
        ]
        assert client.artifacts[0].body != client.artifacts[1].body

    def test_labels_are_stable_regardless_of_parameter_order(
        self, dahua_server, client_factory
    ):
        """The evidence digest sorts on this label, so it must be canonical."""
        client = client_factory(dahua_server)

        client.get(
            "/cgi-bin/configManager.cgi",
            ProbeMethod.DAHUA_CGI,
            name="NTP",
            action="getConfig",
        )

        assert client.artifacts[0].endpoint == (
            "/cgi-bin/configManager.cgi?action=getConfig&name=NTP"
        )

    def test_a_parameterless_request_keeps_its_bare_path(
        self, hikvision_server, client_factory
    ):
        client = client_factory(hikvision_server)

        artifact = client.get(DEVICE_INFO, ProbeMethod.HIKVISION_ISAPI)

        assert artifact.endpoint == DEVICE_INFO

    def test_distinct_actions_now_reach_the_evidence_digest_distinctly(
        self, dahua_server, client_factory
    ):
        """combined_sha256 sorts by endpoint; identical labels made it order-dependent."""
        from vendors.base import EvidenceRecorder

        client = client_factory(dahua_server)
        client.get(MAGICBOX, ProbeMethod.DAHUA_CGI, action="getSystemInfo")
        client.get(MAGICBOX, ProbeMethod.DAHUA_CGI, action="getSerialNo")

        evidence = EvidenceRecorder(ProbeMethod.DAHUA_CGI).finish(client)
        labels = [a.endpoint for a in evidence.artifacts]

        assert len(set(labels)) == len(labels)


class TestFailureBehaviour:
    def test_an_auth_failure_propagates_even_through_the_tolerant_getter(
        self, hikvision_server, client_factory
    ):
        """A wrong password is never a tolerable gap in the record."""
        client = client_factory(hikvision_server, password="wrong")

        with pytest.raises(TransportError) as raised:
            client.try_get(DEVICE_INFO, ProbeMethod.HIKVISION_ISAPI)

        assert raised.value.code is ErrorCode.AUTH_FAILED

    def test_fingerprinting_may_opt_into_tolerating_an_auth_failure(
        self, hikvision_server, client_factory
    ):
        """A 401 before credentials are offered is a signal, not a failure.

        Detection runs unauthenticated, so it has to be able to read a
        challenge without the probe blowing up in its face.
        """
        client = client_factory(hikvision_server, username=None, password=None)

        result = client.try_get(
            DEVICE_INFO, ProbeMethod.UNAUTHENTICATED_FINGERPRINT, tolerate_auth_failure=True
        )

        assert result is None
        # The 401 itself is still retained: it is evidence about the device.
        assert [a.status_code for a in client.artifacts] == [401]

    def test_tolerating_auth_failure_does_not_swallow_a_lockout_warning(
        self, hikvision_server, client_factory
    ):
        """Lockout risk is about retrying, so the retained 401 must show it."""
        hikvision_server.lockout_warning = True
        client = client_factory(hikvision_server, username=None, password=None)

        result = client.try_get(
            DEVICE_INFO, ProbeMethod.UNAUTHENTICATED_FINGERPRINT, tolerate_auth_failure=True
        )

        assert result is None
        assert "attempts remaining" in client.artifacts[0].body

    def test_tolerance_is_opt_in_per_call_not_per_client(
        self, hikvision_server, client_factory
    ):
        client = client_factory(hikvision_server, password="wrong")

        tolerated = client.try_get(
            DEVICE_INFO, ProbeMethod.HIKVISION_ISAPI, tolerate_auth_failure=True
        )
        assert tolerated is None

        with pytest.raises(TransportError):
            client.try_get(DEVICE_INFO, ProbeMethod.HIKVISION_ISAPI)

    def test_a_refused_connection_is_reported_as_unreachable(self, closed_port):
        with HttpDeviceClient("127.0.0.1", closed_port, "admin", "x", timeout=2) as client:
            with pytest.raises(TransportError) as raised:
                client.challenge()

        assert raised.value.code is ErrorCode.UNREACHABLE

    def test_a_stalled_recorder_is_reported_as_a_timeout(self, hikvision_server):
        hikvision_server.response_delay = 2.0

        with make_client(hikvision_server, timeout=0.25) as client:
            with pytest.raises(TransportError) as raised:
                client.challenge()

        assert raised.value.code is ErrorCode.TIMEOUT


class TestStreaming:
    def test_hashes_are_computed_over_the_received_stream(
        self, hikvision_server, client_factory, tmp_path
    ):
        from tests.mock_dvr.hikvision import DOWNLOAD_PAYLOAD

        client = client_factory(hikvision_server)
        destination = tmp_path / "stream.bin"

        written, md5, sha256 = client.stream_to_file(
            "POST", "/ISAPI/ContentMgmt/download", str(destination), data="<downloadRequest/>"
        )

        assert written == len(DOWNLOAD_PAYLOAD)
        assert md5 == hashlib.md5(DOWNLOAD_PAYLOAD).hexdigest()
        assert sha256 == hashlib.sha256(DOWNLOAD_PAYLOAD).hexdigest()
        assert destination.read_bytes() == DOWNLOAD_PAYLOAD

    def test_a_large_body_is_streamed_in_chunks_without_corruption(
        self, hikvision_server, client_factory, tmp_path
    ):
        """The stream is hashed chunk by chunk; the digest must still be whole."""
        payload = bytes(range(256)) * 2048  # 512 KiB, several read chunks
        hikvision_server.download_payload = payload
        client = client_factory(hikvision_server)
        destination = tmp_path / "large.bin"

        written, _md5, sha256 = client.stream_to_file(
            "POST", "/ISAPI/ContentMgmt/download", str(destination), data="<downloadRequest/>"
        )

        assert written == len(payload)
        assert sha256 == hashlib.sha256(payload).hexdigest()

    def test_a_rejected_stream_raises_before_a_file_is_created(
        self, hikvision_server, client_factory, tmp_path
    ):
        hikvision_server.disabled_paths = {"/ISAPI/ContentMgmt/download"}
        client = client_factory(hikvision_server)
        destination = tmp_path / "never.bin"

        with pytest.raises(TransportError) as raised:
            client.stream_to_file(
                "POST", "/ISAPI/ContentMgmt/download", str(destination), data="<x/>"
            )

        assert raised.value.code is ErrorCode.PROTOCOL_ERROR
        assert not destination.exists()

    def test_bad_credentials_during_acquisition_are_an_auth_failure(
        self, hikvision_server, client_factory, tmp_path
    ):
        client = client_factory(hikvision_server, password="wrong")

        with pytest.raises(TransportError) as raised:
            client.stream_to_file(
                "POST", "/ISAPI/ContentMgmt/download", str(tmp_path / "x.bin"), data="<x/>"
            )

        assert raised.value.code is ErrorCode.AUTH_FAILED

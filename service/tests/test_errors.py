"""Failure mapping: telling apart the four ways a probe can go wrong.

"Wrong password", "wrong vendor" and "cable unplugged" lead to completely
different next steps for an investigator, so the codes are asserted
individually rather than as a generic failure.
"""

from datetime import datetime, timezone

import pytest

from models.common import ErrorCode
from models.probe import AcquisitionRequest, RecordingSearchRequest
from services import probe as probe_service
from services.probe import (
    acquire_recording,
    detect_device,
    identify_device,
    search_recordings,
)
from tests.conftest import make_target
from vendors.base import AdapterError
from vendors.godrej import GodrejAdapter
from vendors.transports.http_digest import TransportError

WINDOW_START = datetime(2026, 9, 4, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 9, 5, tzinfo=timezone.utc)


class _Unreachable:
    """A host/port pair with nothing listening, shaped like a mock server."""

    def __init__(self, port: int):
        self.host = "127.0.0.1"
        self.port = port


class TestTransportFailures:
    def test_a_refused_connection_is_unreachable(self, closed_port):
        response = detect_device(make_target(_Unreachable(closed_port)))

        assert response.success is False
        assert response.error.code is ErrorCode.UNREACHABLE
        assert "Could not reach" in response.error.message
        assert "powered on and reachable" in response.error.remediation

    def test_a_stalled_recorder_is_a_timeout_not_an_outage(self, hikvision_server):
        """A timeout means try again with more patience; unreachable does not."""
        hikvision_server.response_delay = 2.0
        target = make_target(hikvision_server)
        target.timeout_seconds = 0.25

        response = detect_device(target)

        assert response.error.code is ErrorCode.TIMEOUT
        assert "Increase the timeout" in response.error.remediation

    def test_wrong_credentials_are_reported_as_an_auth_failure(self, hikvision_server):
        response = identify_device(make_target(hikvision_server, password="wrong"))

        assert response.success is False
        assert response.error.code is ErrorCode.AUTH_FAILED
        assert "Verify the username and password" in response.error.remediation

    def test_a_recorder_counting_failures_raises_the_lockout_alarm(self, hikvision_server):
        """Retrying past this point can lock the account out of its own DVR."""
        hikvision_server.lockout_warning = True

        response = identify_device(make_target(hikvision_server, password="wrong"))

        assert response.error.code is ErrorCode.AUTH_LOCKOUT_RISK
        assert "Stop retrying" in response.error.remediation
        assert "lockout" in response.error.detail

    def test_lockout_risk_is_distinguished_from_a_plain_rejection(self, hikvision_server):
        plain = identify_device(make_target(hikvision_server, password="wrong"))
        hikvision_server.lockout_warning = True
        risky = identify_device(make_target(hikvision_server, password="wrong"))

        assert plain.error.code is ErrorCode.AUTH_FAILED
        assert risky.error.code is ErrorCode.AUTH_LOCKOUT_RISK


class TestVendorFailures:
    def test_an_unrecognised_device_is_unsupported_not_broken(self, blank_server):
        response = detect_device(make_target(blank_server))

        assert response.error.code is ErrorCode.UNSUPPORTED_VENDOR
        assert response.detection.vendor.value == "UNKNOWN"
        assert "Candidates considered" in response.error.detail

    def test_identification_of_an_unrecognised_device_stops_early(self, blank_server):
        response = identify_device(make_target(blank_server))

        assert response.success is False
        assert response.error.code is ErrorCode.UNSUPPORTED_VENDOR
        assert response.device is None

    def test_searching_an_unrecognised_device_stops_early(self, blank_server):
        response = search_recordings(
            RecordingSearchRequest(
                target=make_target(blank_server), start=WINDOW_START, end=WINDOW_END
            )
        )

        assert response.error.code is ErrorCode.UNSUPPORTED_VENDOR

    def test_an_empty_search_window_is_a_protocol_error(self, hikvision_server):
        response = search_recordings(
            RecordingSearchRequest(
                target=make_target(hikvision_server), start=WINDOW_END, end=WINDOW_START
            )
        )

        assert response.error.code is ErrorCode.PROTOCOL_ERROR
        assert "later than start time" in response.error.message


class TestCapabilityFailures:
    def test_an_unsupported_capability_says_so_rather_than_returning_nothing(self):
        """A capability gap is a property of the protocol, not a bug."""
        with pytest.raises(AdapterError) as raised:
            GodrejAdapter().search_recordings(None, ["1"], WINDOW_START, WINDOW_END)

        assert raised.value.code is ErrorCode.CAPABILITY_UNAVAILABLE
        assert "GODREJ" in raised.value.message
        assert "limitation of the vendor's published protocol" in raised.value.detail

    def test_acquisition_is_refused_for_an_adapter_that_cannot_export(self):
        with pytest.raises(AdapterError) as raised:
            GodrejAdapter().download_recording(
                None, "/tmp/x.bin", "rec-1", "1", WINDOW_START, WINDOW_END
            )

        assert raised.value.code is ErrorCode.CAPABILITY_UNAVAILABLE


class TestUnexpectedFailures:
    def test_an_unexpected_exception_becomes_an_internal_error(
        self, hikvision_server, monkeypatch
    ):
        """An internal fault must still leave the envelope intact."""

        def explode(*args, **kwargs):
            raise ValueError("adapter registry is on fire")

        monkeypatch.setattr(probe_service, "detect", explode)

        response = detect_device(make_target(hikvision_server))

        assert response.success is False
        assert response.error.code is ErrorCode.INTERNAL
        assert "adapter registry is on fire" in response.error.detail

    def test_an_acquisition_failure_is_mapped_and_leaves_nothing_behind(
        self, hikvision_server, evidence_dir
    ):
        import os

        hikvision_server.disabled_paths = {"/ISAPI/ContentMgmt/download"}

        response = acquire_recording(
            AcquisitionRequest(
                target=make_target(hikvision_server),
                recording_id="rec-1",
                channel_id="1",
                start=WINDOW_START,
                end=WINDOW_END,
                playback_uri=hikvision_server.playback_uri(0),
            )
        )

        assert response.success is False
        assert response.error.code is ErrorCode.PROTOCOL_ERROR
        assert os.listdir(evidence_dir) == []


class TestErrorCodeCoverage:
    """Every code the transport can raise must map to a stable envelope."""

    @pytest.mark.parametrize(
        "code, expects_remediation",
        [
            (ErrorCode.UNREACHABLE, True),
            (ErrorCode.TIMEOUT, True),
            (ErrorCode.AUTH_FAILED, True),
            (ErrorCode.AUTH_LOCKOUT_RISK, True),
            (ErrorCode.PROTOCOL_ERROR, False),
        ],
    )
    def test_transport_errors_carry_their_code_through(self, code, expects_remediation):
        error = probe_service._error(TransportError(code, "message", "detail"))

        assert error.code is code
        assert error.message == "message"
        assert error.detail == "detail"
        assert bool(error.remediation) is expects_remediation

    def test_adapter_errors_carry_their_code_through(self):
        error = probe_service._error(
            AdapterError(ErrorCode.CAPABILITY_UNAVAILABLE, "no", "because")
        )

        assert error.code is ErrorCode.CAPABILITY_UNAVAILABLE
        assert error.detail == "because"

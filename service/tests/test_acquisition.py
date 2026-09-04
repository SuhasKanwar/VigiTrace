"""Controlled export: the bytes, their hashes, and the claims made about them.

The hashes are the only integrity claim the software can honestly support, so
they are checked against hashlib over the exact payload the mock served rather
than against themselves.
"""

import hashlib
import os
from datetime import datetime, timezone

import pytest

from models.probe import AcquisitionRequest
from services.probe import acquire_recording
from tests.conftest import make_target
from tests.mock_dvr import dahua as dahua_mock
from tests.mock_dvr import hikvision as hik_mock
from vendors.base import AdapterError
from vendors.dahua import DahuaAdapter
from vendors.hikvision import HikvisionAdapter
from vendors.transports.http_digest import TransportError

SPAN_START = datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
SPAN_END = datetime(2026, 9, 4, 9, 0, tzinfo=timezone.utc)


def expected_hashes(payload: bytes) -> tuple[str, str]:
    return hashlib.md5(payload).hexdigest(), hashlib.sha256(payload).hexdigest()


class TestHikvisionAcquisition:
    def test_bytes_are_written_and_hashed(self, hik_client, hikvision_server, tmp_path):
        destination = tmp_path / "segment.bin"

        result = HikvisionAdapter().download_recording(
            hik_client,
            str(destination),
            "rec-1",
            "101",
            SPAN_START,
            SPAN_END,
            playback_uri=hikvision_server.playback_uri(0),
        )

        md5, sha256 = expected_hashes(hik_mock.DOWNLOAD_PAYLOAD)
        assert destination.read_bytes() == hik_mock.DOWNLOAD_PAYLOAD
        assert result.size_bytes == len(hik_mock.DOWNLOAD_PAYLOAD)
        assert result.md5 == md5
        assert result.sha256 == sha256
        assert result.container == "MPEG-PS (Hikvision IMKH)"
        assert result.stored_path == str(destination)
        assert result.duration_ms >= 0

    def test_the_indexed_playback_uri_is_echoed_back_verbatim(
        self, hik_client, hikvision_server, tmp_path
    ):
        """Re-deriving the URI risks exporting a different segment."""
        uri = hikvision_server.playback_uri(1)

        result = HikvisionAdapter().download_recording(
            hik_client, str(tmp_path / "s.bin"), "rec-2", "101", SPAN_START, SPAN_END,
            playback_uri=uri,
        )

        body = hikvision_server.calls_to("/ISAPI/ContentMgmt/download")[-1].text
        assert f"<playbackURI>{uri}</playbackURI>" in body
        assert result.source_uri == uri

    def test_a_size_mismatch_is_warned_about(self, hik_client, hikvision_server, tmp_path):
        """The index advertises an exact length; a short export is not it."""
        result = HikvisionAdapter().download_recording(
            hik_client, str(tmp_path / "s.bin"), "rec-1", "101", SPAN_START, SPAN_END,
            playback_uri=hikvision_server.playback_uri(0),
        )

        assert result.warnings == [
            f"Recorder advertised 260358144 bytes but "
            f"{len(hik_mock.DOWNLOAD_PAYLOAD)} were received."
        ]

    def test_a_matching_size_produces_no_warning(self, hik_client, tmp_path):
        uri = (
            "rtsp://127.0.0.1/Streaming/tracks/101/?starttime=20260904T080000Z"
            f"&endtime=20260904T090000Z&name=ch01&size={len(hik_mock.DOWNLOAD_PAYLOAD)}"
        )

        result = HikvisionAdapter().download_recording(
            hik_client, str(tmp_path / "s.bin"), "rec-1", "101", SPAN_START, SPAN_END,
            playback_uri=uri,
        )

        assert result.warnings == []

    def test_acquisition_without_an_indexed_uri_is_refused(self, hik_client, tmp_path):
        with pytest.raises(AdapterError) as raised:
            HikvisionAdapter().download_recording(
                hik_client, str(tmp_path / "s.bin"), "rec-1", "101", SPAN_START, SPAN_END
            )

        assert raised.value.code.value == "PROTOCOL_ERROR"
        assert "recording search" in (raised.value.detail or "")

    def test_a_refused_export_does_not_leave_a_file_behind(
        self, hikvision_server, client_factory, tmp_path
    ):
        hikvision_server.disabled_paths = {"/ISAPI/ContentMgmt/download"}
        client = client_factory(hikvision_server)
        destination = tmp_path / "s.bin"

        with pytest.raises(TransportError) as raised:
            HikvisionAdapter().download_recording(
                client, str(destination), "rec-1", "101", SPAN_START, SPAN_END,
                playback_uri=hikvision_server.playback_uri(0),
            )

        assert raised.value.code.value == "PROTOCOL_ERROR"
        assert not destination.exists()


class TestDahuaAcquisition:
    def test_bytes_are_written_and_hashed(self, dahua_client, dahua_server, tmp_path):
        destination = tmp_path / "segment.dav"

        result = DahuaAdapter().download_recording(
            dahua_client,
            str(destination),
            "rec-1",
            "1",
            SPAN_START,
            SPAN_END,
            file_path=dahua_server.file_path(0),
        )

        md5, sha256 = expected_hashes(dahua_mock.DOWNLOAD_PAYLOAD)
        assert destination.read_bytes() == dahua_mock.DOWNLOAD_PAYLOAD
        assert result.size_bytes == len(dahua_mock.DOWNLOAD_PAYLOAD)
        assert result.md5 == md5
        assert result.sha256 == sha256
        assert result.container == "DHAV"

    def test_the_on_device_path_is_the_locator(self, dahua_client, dahua_server, tmp_path):
        path = dahua_server.file_path(2)

        result = DahuaAdapter().download_recording(
            dahua_client, str(tmp_path / "s.dav"), "rec-3", "1", SPAN_START, SPAN_END,
            file_path=path,
        )

        assert result.source_uri == f"/cgi-bin/RPC_Loadfile{path}"
        assert any(
            request.path == f"/cgi-bin/RPC_Loadfile{path}" for request in dahua_server.requests
        )

    def test_a_relative_locator_is_refused(self, dahua_client, tmp_path):
        """Only an absolute on-device path can address a Dahua recording."""
        with pytest.raises(AdapterError) as raised:
            DahuaAdapter().download_recording(
                dahua_client, str(tmp_path / "s.dav"), "rec-1", "1", SPAN_START, SPAN_END,
                file_path="dav/08.00.00.dav",
            )

        assert raised.value.code.value == "PROTOCOL_ERROR"


class TestAcquisitionService:
    """The orchestration layer: naming, storage location, failure cleanup."""

    def test_a_successful_acquisition_lands_in_the_evidence_directory(
        self, hikvision_server, evidence_dir
    ):
        request = AcquisitionRequest(
            target=make_target(hikvision_server),
            recording_id="rec-1",
            channel_id="101",
            start=SPAN_START,
            end=SPAN_END,
            playback_uri=hikvision_server.playback_uri(0),
        )

        response = acquire_recording(request)

        assert response.success is True
        assert response.acquisition is not None
        stored = response.acquisition.stored_path
        assert stored.startswith(str(evidence_dir))
        assert os.path.getsize(stored) == len(hik_mock.DOWNLOAD_PAYLOAD)
        md5, sha256 = expected_hashes(hik_mock.DOWNLOAD_PAYLOAD)
        assert response.acquisition.md5 == md5
        assert response.acquisition.sha256 == sha256

    def test_the_stored_name_is_derived_safely_from_the_channel(
        self, hikvision_server, evidence_dir
    ):
        """A channel id from the device must never escape the evidence path."""
        request = AcquisitionRequest(
            target=make_target(hikvision_server),
            recording_id="rec-1",
            channel_id="../../etc/101",
            start=SPAN_START,
            end=SPAN_END,
            playback_uri=hikvision_server.playback_uri(0),
        )

        response = acquire_recording(request)

        assert response.success is True
        stored = response.acquisition.stored_path
        # Path separators are scrubbed, so the traversal cannot leave the
        # evidence directory even though the dots survive in the file name.
        assert os.path.dirname(stored) == str(evidence_dir)
        assert os.sep not in os.path.basename(stored)
        assert os.path.realpath(stored).startswith(os.path.realpath(str(evidence_dir)))

    def test_a_failed_acquisition_leaves_no_partial_evidence(
        self, hikvision_server, evidence_dir
    ):
        hikvision_server.disabled_paths = {"/ISAPI/ContentMgmt/download"}
        request = AcquisitionRequest(
            target=make_target(hikvision_server),
            recording_id="rec-1",
            channel_id="101",
            start=SPAN_START,
            end=SPAN_END,
            playback_uri=hikvision_server.playback_uri(0),
        )

        response = acquire_recording(request)

        assert response.success is False
        assert response.error.code.value == "PROTOCOL_ERROR"
        assert os.listdir(evidence_dir) == []

    def test_an_unknown_vendor_is_not_acquired_from(self, blank_server, evidence_dir):
        request = AcquisitionRequest(
            target=make_target(blank_server),
            recording_id="rec-1",
            channel_id="1",
            start=SPAN_START,
            end=SPAN_END,
            file_path="/mnt/dvr/x.dav",
        )

        response = acquire_recording(request)

        assert response.success is False
        assert response.error.code.value == "UNSUPPORTED_VENDOR"
        assert os.listdir(evidence_dir) == []

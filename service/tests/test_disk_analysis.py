"""End-to-end tests for the disk-analysis service and its HTTP surface.

These sit a layer above ``tests/test_disk_hikvision.py``: they check that
reader, carve, and recovery are wired together correctly by the service - the
source image stays untouched, carved output lands under the evidence tree
rather than beside the input, limits are honoured and reported, and errors
carry a code and a useful message - rather than re-testing the format parsing
itself.
"""

import os

import pytest

from disk.hikvision import layout as L
from disk.hikvision.carve import ffprobe_available
from models.common import ErrorCode
from services.disk_analysis import DiskAnalysisError, analyse_image, hash_image
from tests.disk.hikvision_image import HikvisionImageBuilder
from tests.disk.video import build_program_stream_map, ffmpeg_available, make_program_stream

BASE_TIME = 1_700_000_000
BLOCK_SIZE = 1 << 18


def _synthetic_video(pack_count: int = 3) -> bytes:
    """Bytes with genuine pack-header/PSM magic but no real H.264 payload.

    Enough for carve/recovery's byte-pattern logic (and for a segment to come
    out of ``carve_block``) without paying for an ffmpeg encode. Tests that
    need a real decode say so and are gated on ffmpeg/ffprobe being present.
    """
    psm = build_program_stream_map()
    chunk = L.PS_PACK_HEADER + b"\x00" * 8 + psm
    return chunk * pack_count


def _build_image(directory, name: str, recordings: list[dict]) -> str:
    """One data block per recording, indexed or not - matches the builder's own rule."""
    builder = HikvisionImageBuilder(block_size=BLOCK_SIZE, block_count=len(recordings), init_time=BASE_TIME)
    for recording in recordings:
        builder.add_recording(**recording)
    return builder.write(str(directory / name))


@pytest.fixture
def disk_evidence_dir(tmp_path, monkeypatch):
    """Redirect carved artifacts into the test's own tree.

    Without this, ``analyse_image(carve=True)`` would create directories
    under the repository's real ``evidence/`` folder every time this suite ran.
    """
    destination = tmp_path / "evidence"
    monkeypatch.setattr("services.disk_analysis.EVIDENCE_DIR", str(destination))
    return destination


class TestAnalyseImageEndToEnd:
    @pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg is not installed")
    @pytest.mark.skipif(not ffprobe_available(), reason="ffprobe is not installed")
    def test_counts_hash_gaps_recovered_blocks_and_decoded_artifacts(self, tmp_path, disk_evidence_dir):
        video = make_program_stream(seconds=1, width=160, height=120, fps=10, with_maps=True)
        image_path = _build_image(
            tmp_path,
            "endtoend.img",
            recordings=[
                dict(channel=1, start=BASE_TIME, end=BASE_TIME + 2, payload=video),
                dict(channel=1, start=BASE_TIME + 300, end=BASE_TIME + 302, payload=video),
                dict(channel=2, start=BASE_TIME + 900, end=BASE_TIME + 902, payload=video, orphaned=True),
            ],
        )

        evidence = analyse_image(image_path, carve=True, carve_limit=10, compute_hash=True, verify_decode=True)

        assert evidence.image_sha256 == hash_image(image_path)
        assert len(evidence.recordings) == 2
        assert evidence.channels_present == [1]  # the orphaned channel-2 block is not indexed

        assert len(evidence.gaps) == 1
        gap = evidence.gaps[0]
        assert gap.channel == 1
        assert gap.duration_seconds == pytest.approx(298.0)

        assert len(evidence.recovered_blocks) == 1
        recovered = evidence.recovered_blocks[0]
        assert recovered.channel == 2
        assert recovered.confidence == "STRONG"

        assert len(evidence.artifacts) == 3  # 2 indexed + 1 recovered, all within carve_limit
        for artifact in evidence.artifacts:
            assert artifact.decoded is True
            assert artifact.codec == "h264"
            assert artifact.frames is not None and artifact.frames > 0


class TestCarveDisabled:
    def test_no_artifacts_when_carve_is_false(self, tmp_path):
        image_path = _build_image(
            tmp_path,
            "nocarve.img",
            recordings=[dict(channel=1, start=BASE_TIME, end=BASE_TIME + 30, payload=_synthetic_video())],
        )

        evidence = analyse_image(image_path, carve=False)

        assert evidence.artifacts == []


class TestCarveLimit:
    def test_limit_is_honoured_and_truncation_is_reported(self, tmp_path, disk_evidence_dir):
        recordings = [
            dict(channel=i, start=BASE_TIME + i * 100, end=BASE_TIME + i * 100 + 30, payload=_synthetic_video())
            for i in range(1, 4)
        ] + [
            dict(
                channel=10 + i, start=BASE_TIME + 5000 + i * 100, end=BASE_TIME + 5000 + i * 100 + 30,
                payload=_synthetic_video(), orphaned=True,
            )
            for i in range(2)
        ]
        image_path = _build_image(tmp_path, "limit.img", recordings)

        evidence = analyse_image(image_path, carve=True, carve_limit=2, verify_decode=False)

        assert len(evidence.artifacts) == 2
        assert "5 block(s) were eligible for carving; the first 2 were extracted." in " ".join(evidence.warnings)


class TestAnalyseImageErrors:
    def test_missing_path_raises_with_a_useful_message(self, tmp_path):
        missing_path = str(tmp_path / "does-not-exist.img")

        with pytest.raises(DiskAnalysisError) as excinfo:
            analyse_image(missing_path)

        # IMAGE_UNREADABLE, not NOT_CONFIGURED: nothing is misconfigured and
        # nothing upstream failed - the caller named a path that is not there.
        assert excinfo.value.code == ErrorCode.IMAGE_UNREADABLE
        assert "readable image" in excinfo.value.message.lower()

    def test_non_recorder_file_raises_with_a_useful_message(self, tmp_path):
        garbage_path = tmp_path / "garbage.bin"
        garbage_path.write_bytes(os.urandom(4096))

        with pytest.raises(DiskAnalysisError) as excinfo:
            analyse_image(str(garbage_path))

        assert excinfo.value.code == ErrorCode.UNSUPPORTED_VENDOR
        assert "signature" in excinfo.value.message.lower()


class TestDerivedArtifactLocation:
    def test_carved_output_lands_under_evidence_dir_not_beside_the_source(self, tmp_path, disk_evidence_dir):
        source_dir = tmp_path / "source"
        source_dir.mkdir()
        image_path = _build_image(
            source_dir,
            "acquired.img",
            recordings=[dict(channel=1, start=BASE_TIME, end=BASE_TIME + 30, payload=_synthetic_video())],
        )

        before_listing = set(os.listdir(source_dir))
        before_bytes = open(image_path, "rb").read()
        before_mtime_ns = os.stat(image_path).st_mtime_ns

        evidence = analyse_image(image_path, carve=True, verify_decode=False)

        assert len(evidence.artifacts) == 1
        artifact = evidence.artifacts[0]
        assert os.path.dirname(artifact.stored_path) != os.path.dirname(image_path)
        assert artifact.stored_path.startswith(str(disk_evidence_dir))
        assert os.path.exists(artifact.stored_path)

        # Carving must be the only side effect: nothing new beside the source,
        # and the source's own bytes/mtime unchanged - it is evidence, not scratch space.
        assert set(os.listdir(source_dir)) == before_listing
        assert open(image_path, "rb").read() == before_bytes
        assert os.stat(image_path).st_mtime_ns == before_mtime_ns


class TestIdentifyEndpoint:
    def test_success_for_a_real_image(self, tmp_path, api_client):
        image_path = _build_image(tmp_path, "identify.img", recordings=[])

        response = api_client.post("/api/disk/identify", json={"path": image_path})

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["vendor"] == "HIKVISION"

    def test_failure_for_garbage(self, tmp_path, api_client):
        garbage_path = tmp_path / "notarecorder.bin"
        garbage_path.write_bytes(os.urandom(4096))

        response = api_client.post("/api/disk/identify", json={"path": str(garbage_path)})

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert body["data"]["vendor"] == "UNKNOWN"


class TestAnalyseEndpoint:
    def test_success_envelope(self, tmp_path, api_client):
        image_path = _build_image(tmp_path, "analyse_ok.img", recordings=[])

        response = api_client.post("/api/disk/analyse", json={"path": image_path, "carve": False})

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["error"] is None
        assert body["evidence"]["identity"]["vendor"] == "HIKVISION"
        assert body["evidence"]["recordings"] == []

    def test_failure_envelope_for_a_missing_path(self, tmp_path, api_client):
        missing_path = str(tmp_path / "nope.img")

        response = api_client.post("/api/disk/analyse", json={"path": missing_path})

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is False
        assert body["evidence"] is None
        assert body["error"]["code"] == "IMAGE_UNREADABLE"

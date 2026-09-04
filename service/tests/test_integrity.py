"""Integrity primitives: what the hashes do and do not establish.

A hash here proves a stored artifact is byte-identical to what was received.
These tests check that narrow claim holds exactly - including that a single
flipped byte breaks it.
"""

import hashlib

import pytest

from models.common import ProbeMethod
from services.integrity import evidence_digest, hash_file, verify_file
from tests import factories

PAYLOAD = b"IMKH" + bytes(range(256)) * 8


@pytest.fixture
def artifact_file(tmp_path):
    path = tmp_path / "segment.bin"
    path.write_bytes(PAYLOAD)
    return path


def test_hashes_match_hashlib_over_the_same_bytes(artifact_file):
    result = hash_file(str(artifact_file))

    assert result["size_bytes"] == len(PAYLOAD)
    assert result["md5"] == hashlib.md5(PAYLOAD).hexdigest()
    assert result["sha256"] == hashlib.sha256(PAYLOAD).hexdigest()
    assert result["path"] == str(artifact_file)
    assert result["hashed_at"].endswith("+00:00")


def test_a_file_larger_than_one_chunk_is_hashed_whole(tmp_path):
    """The reader loops in 1 MiB chunks; the digest must cover every chunk."""
    payload = bytes(range(256)) * 8192  # 2 MiB, two chunks plus a remainder
    path = tmp_path / "large.bin"
    path.write_bytes(payload)

    result = hash_file(str(path))

    assert result["size_bytes"] == len(payload)
    assert result["sha256"] == hashlib.sha256(payload).hexdigest()


def test_an_empty_file_still_hashes(tmp_path):
    path = tmp_path / "empty.bin"
    path.write_bytes(b"")

    result = hash_file(str(path))

    assert result["size_bytes"] == 0
    assert result["sha256"] == hashlib.sha256(b"").hexdigest()


def test_verification_passes_for_an_untouched_artifact(artifact_file):
    expected = hashlib.sha256(PAYLOAD).hexdigest()

    result = verify_file(str(artifact_file), expected)

    assert result["verified"] is True
    assert result["reason"] is None
    assert result["actual_sha256"] == expected
    assert result["size_bytes"] == len(PAYLOAD)


def test_verification_fails_when_a_single_byte_changes(artifact_file):
    expected = hashlib.sha256(PAYLOAD).hexdigest()
    tampered = bytearray(PAYLOAD)
    tampered[10] ^= 0x01
    artifact_file.write_bytes(bytes(tampered))

    result = verify_file(str(artifact_file), expected)

    assert result["verified"] is False
    assert result["expected_sha256"] == expected
    assert result["actual_sha256"] != expected
    assert "does not match" in result["reason"]


def test_a_missing_artifact_is_reported_as_missing_not_as_mismatched(tmp_path):
    """'Gone' and 'altered' are different findings and must not be conflated."""
    result = verify_file(str(tmp_path / "absent.bin"), "0" * 64)

    assert result["verified"] is False
    assert "missing from storage" in result["reason"]
    assert "actual_sha256" not in result


class TestEvidenceDigest:
    """One digest over a set of payloads, independent of collection order."""

    def test_order_does_not_change_the_digest(self):
        payloads = ["<DeviceInfo/>", "<hddList/>", "<Time/>"]

        assert evidence_digest(payloads) == evidence_digest(list(reversed(payloads)))
        assert evidence_digest(payloads) == evidence_digest(
            [payloads[1], payloads[2], payloads[0]]
        )

    def test_content_does_change_the_digest(self):
        base = ["<DeviceInfo/>", "<hddList/>"]

        assert evidence_digest(base) != evidence_digest(["<DeviceInfo/>", "<hddList></hddList>"])

    def test_an_extra_payload_changes_the_digest(self):
        base = ["<DeviceInfo/>"]

        assert evidence_digest(base) != evidence_digest(base + ["<Time/>"])

    def test_an_empty_set_has_a_stable_digest(self):
        assert evidence_digest([]) == hashlib.sha256().hexdigest()

    def test_non_ascii_payloads_are_handled(self):
        assert len(evidence_digest(["<name>Café</name>"])) == 64


class TestCombinedEvidenceDigest:
    """ProbeEvidence rolls its artifacts up the same way."""

    def test_digest_is_independent_of_the_order_endpoints_answered_in(self):
        first = factories.artifact("/a", "<A/>")
        second = factories.artifact("/b", "<B/>")

        forwards = factories.evidence(artifacts=[first, second])
        backwards = factories.evidence(artifacts=[second, first])

        assert forwards.combined_sha256 == backwards.combined_sha256

    def test_digest_changes_when_a_payload_changes(self):
        original = factories.evidence(artifacts=[factories.artifact("/a", "<A/>")])
        altered = factories.evidence(artifacts=[factories.artifact("/a", "<A>1</A>")])

        assert original.combined_sha256 != altered.combined_sha256

    def test_digest_covers_the_artifact_hashes_not_the_bodies(self):
        artifacts = [factories.artifact("/a", "<A/>"), factories.artifact("/b", "<B/>")]
        expected = hashlib.sha256()
        for item in sorted(artifacts, key=lambda a: a.endpoint):
            expected.update(item.sha256.encode("ascii"))

        assert factories.evidence(artifacts=artifacts).combined_sha256 == expected.hexdigest()


def test_a_real_acquisition_verifies_against_its_recorded_digest(
    hikvision_server, hik_client, tmp_path
):
    """End to end: export, then re-verify the stored file independently."""
    from vendors.hikvision import HikvisionAdapter
    from datetime import datetime, timezone

    destination = tmp_path / "acquired.bin"
    result = HikvisionAdapter().download_recording(
        hik_client,
        str(destination),
        "rec-1",
        "1",
        datetime(2026, 9, 4, 8, tzinfo=timezone.utc),
        datetime(2026, 9, 4, 9, tzinfo=timezone.utc),
        playback_uri=hikvision_server.playback_uri(0),
    )

    verification = verify_file(result.stored_path, result.sha256)

    assert verification["verified"] is True
    assert hash_file(result.stored_path)["md5"] == result.md5


def test_probe_method_is_carried_on_every_artifact():
    """Provenance includes how a payload was obtained, not just what it said."""
    evidence = factories.evidence(
        artifacts=[factories.artifact("/x", "<X/>", ProbeMethod.DAHUA_CGI)]
    )

    assert evidence.artifacts[0].method is ProbeMethod.DAHUA_CGI

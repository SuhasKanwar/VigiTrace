"""Hikvision recording search: the recorder's own index, and its holes.

Gaps matter more than segments here. A gap is where deleted or unindexed
footage would sit, so the index is only useful if the parser preserves segment
boundaries exactly as the recorder reported them.
"""

from datetime import datetime, timezone

import pytest

from models.common import ProbeMethod
from tests.mock_dvr import hikvision as mock
from vendors.hikvision import HikvisionAdapter

WINDOW_START = datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)


def search(client, channels=None, max_results=200):
    return HikvisionAdapter().search_recordings(
        client, channels if channels is not None else ["1"], WINDOW_START, WINDOW_END, max_results
    )


def test_every_segment_in_the_match_list_is_parsed(hik_client):
    index = search(hik_client)

    assert len(index.recordings) == 3
    assert index.searched_span.start == WINDOW_START
    assert index.searched_span.end == WINDOW_END
    assert index.channels_searched == ["1"]
    assert index.truncated is False
    assert index.warnings == []


def test_segment_boundaries_survive_parsing(hik_client):
    first, second, third = search(hik_client).recordings

    assert first.span.start == datetime(2026, 9, 4, 8, 0, tzinfo=timezone.utc)
    assert first.span.end == datetime(2026, 9, 4, 9, 0, tzinfo=timezone.utc)
    assert first.span.duration_seconds == 3600
    assert second.span.end == datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
    assert third.span.start == datetime(2026, 9, 4, 10, 30, tzinfo=timezone.utc)


def test_size_is_extracted_from_the_playback_uri(hik_client):
    """Hikvision hides the exact byte length in the playbackURI query string."""
    recordings = search(hik_client).recordings

    assert [r.size_bytes for r in recordings] == [size for _s, _e, size in mock.SEGMENTS]
    assert recordings[0].playback_uri.endswith("size=260358144")
    assert search(hik_client).total_bytes == sum(s for _a, _b, s in mock.SEGMENTS)


def test_codec_and_provenance_are_carried_through(hik_client):
    recording = search(hik_client).recordings[0]

    assert recording.codec == "H.264-BP"
    assert recording.source_method is ProbeMethod.HIKVISION_ISAPI
    # The recorder indexes by track; the pipeline joins on channel, so both are
    # kept and the vendor-native locator does not leak into channel_id.
    assert recording.track_id == "101"
    assert recording.channel_id == "1"
    assert recording.recording_id == "{00000001-0000-0000-0000-000000000000}"
    # The verbatim match item is retained alongside the normalized view.
    assert recording.raw["mediaSegmentDescriptor"]["codecType"] == "H.264-BP"


def test_the_gap_between_segments_is_found(hik_client):
    """The mock deliberately omits 10:00-10:30; the index must surface it."""
    index = search(hik_client)

    gaps = index.gaps("1")

    assert len(gaps) == 1
    assert gaps[0].start == datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
    assert gaps[0].end == datetime(2026, 9, 4, 10, 30, tzinfo=timezone.utc)
    assert gaps[0].duration_seconds == mock.GAP_SECONDS


def test_gaps_are_per_channel(hik_client):
    index = search(hik_client)

    assert index.gaps("999") == []


def test_a_single_match_is_not_collapsed_away(hikvision_server, client_factory):
    """One result arrives as a bare dict from xmltodict, not a one-item list."""
    hikvision_server.single_match = True
    client = client_factory(hikvision_server)

    index = search(client)

    assert len(index.recordings) == 1
    assert index.gaps("1") == []


def test_truncation_reported_by_the_recorder_is_propagated(
    hikvision_server, client_factory
):
    """A capped result set must never look like a complete one."""
    hikvision_server.more_results = True
    client = client_factory(hikvision_server)

    index = search(client)

    assert index.truncated is True


def test_channel_ids_are_translated_into_track_ids_on_the_wire(
    hikvision_server, hik_client
):
    search(hik_client, channels=["2"])

    body = hikvision_server.calls_to("/ISAPI/ContentMgmt/search")[-1].text
    assert "<trackID>201</trackID>" in body


def test_search_window_is_sent_in_utc(hikvision_server, hik_client):
    """Recorders answer in local time; the query at least is unambiguous."""
    search(hik_client)

    body = hikvision_server.calls_to("/ISAPI/ContentMgmt/search")[-1].text
    assert "<startTime>2026-09-04T00:00:00Z</startTime>" in body
    assert "<endTime>2026-09-05T00:00:00Z</endTime>" in body


def test_the_vendors_own_misspelling_is_preserved(hikvision_server, hik_client):
    """'searchResultPostion' is misspelled in the ISAPI spec and on the device."""
    search(hik_client)

    body = hikvision_server.calls_to("/ISAPI/ContentMgmt/search")[-1].text
    assert "searchResultPostion" in body
    assert "searchResultPosition" not in body


def test_no_channels_falls_back_to_the_first_track(hikvision_server, hik_client):
    search(hik_client, channels=[])

    body = hikvision_server.calls_to("/ISAPI/ContentMgmt/search")[-1].text
    assert "<trackID>101</trackID>" in body


def test_a_failed_search_is_warned_about_rather_than_returned_as_empty(
    hikvision_server, client_factory
):
    """An HTTP error must not be indistinguishable from 'nothing recorded'."""
    hikvision_server.disabled_paths = {"/ISAPI/ContentMgmt/search"}
    client = client_factory(hikvision_server)

    index = search(client)

    assert index.recordings == []
    assert any("Search failed" in warning for warning in index.warnings)


def test_max_results_is_passed_to_the_recorder(hikvision_server, hik_client):
    search(hik_client, max_results=25)

    body = hikvision_server.calls_to("/ISAPI/ContentMgmt/search")[-1].text
    assert "<maxResults>25</maxResults>" in body


@pytest.mark.parametrize(
    "uri, expected",
    [
        ("rtsp://h/t/101/?starttime=x&size=1024", 1024),
        ("rtsp://h/t/101/?starttime=x", None),
        (None, None),
    ],
)
def test_size_parsing_tolerates_missing_parameters(uri, expected):
    assert HikvisionAdapter._size_from_uri(uri) == expected

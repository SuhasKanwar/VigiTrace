"""Dahua recording search and the finder-handle lifecycle.

Dahua's media search allocates an object on the recorder that must be closed
and destroyed. Leaking it degrades the device an investigator is trying not to
disturb, so the cleanup is asserted on the failure path as well as the happy
one.
"""

from datetime import datetime, timedelta, timezone

import pytest

from models.common import ProbeMethod
from tests.mock_dvr import dahua as mock
from vendors.dahua import MEDIA_FILE_FIND, DahuaAdapter
from vendors.hikvision import HikvisionAdapter

WINDOW_START = datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)


def search(client, channels=("1",), max_results=200):
    return DahuaAdapter().search_recordings(
        client, list(channels), WINDOW_START, WINDOW_END, max_results
    )


def unique_actions(server):
    """Digest auth doubles every request; collapse the retry duplicates."""
    seen: list[str] = []
    for action in server.actions(MEDIA_FILE_FIND):
        if not seen or seen[-1] != action:
            seen.append(action)
    return seen


def test_every_indexed_file_is_parsed(dahua_client):
    index = search(dahua_client)

    assert len(index.recordings) == 3
    assert index.channels_searched == ["1"]
    assert index.truncated is False


def test_file_metadata_is_carried_through(dahua_client):
    recording = search(dahua_client).recordings[0]

    assert recording.channel_id == "1"
    assert recording.file_path.endswith("08.00.00-09.00.00.dav")
    assert recording.recording_id == recording.file_path
    assert recording.codec == "dav"
    assert recording.size_bytes == 104857600
    assert recording.event_type == "VideoMotion"
    assert recording.source_method is ProbeMethod.DAHUA_CGI
    assert recording.raw["Cluster"] == "1"


def test_overwrite_count_is_preserved(dahua_client):
    """How often a region was reused speaks directly to what is recoverable."""
    recordings = search(dahua_client).recordings

    assert [r.overwrite_count for r in recordings] == [5, 0, 0]


def test_record_trigger_comes_from_the_indexed_flags(dahua_client):
    """Why a segment exists at all - timed, manual, or event-driven.

    The recorder encodes it as ``items[0].Flags[0]=Timing``, so parse_kv yields
    a list; reading only a bare string would drop the field on every real
    device.
    """
    recording = search(dahua_client).recordings[0]

    assert recording.raw["Flags"] == ["Timing"]
    assert recording.record_trigger == "Timing"


def test_a_flag_reported_as_a_bare_string_is_still_read(dahua_server, client_factory):
    """Firmware varies on whether the field is indexed; both forms must work."""
    dahua_server.scalar_flags = True
    client = client_factory(dahua_server)

    recording = search(client).recordings[0]

    assert recording.raw["Flags"] == "Manual"
    assert recording.record_trigger == "Manual"


def test_the_gap_between_segments_is_found(dahua_client):
    index = search(dahua_client)

    gaps = index.gaps("1")

    assert len(gaps) == 1
    assert gaps[0].duration_seconds == mock.GAP_SECONDS
    assert gaps[0].start == datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)


def test_search_condition_is_sent_in_the_recorders_own_time_format(
    dahua_server, dahua_client
):
    search(dahua_client)

    find = [r for r in dahua_server.calls_to(MEDIA_FILE_FIND) if r.query.get("action") == "findFile"]
    assert find
    assert find[-1].query["condition.Channel"] == "1"
    assert find[-1].query["condition.StartTime"] == "2026-09-04 00:00:00"
    assert find[-1].query["condition.EndTime"] == "2026-09-05 00:00:00"
    assert find[-1].query["object"] == mock.FINDER_HANDLE


def test_the_search_window_is_normalised_to_utc(dahua_server, dahua_client):
    """One instant must produce one query, whatever zone the caller used.

    Dahua accepts wall-clock with no zone attached, so an unconverted local
    time would silently search a different window than the same call made from
    another timezone - and a different window than the Hikvision adapter, which
    converts.
    """
    tzinfo = timezone(timedelta(hours=5, minutes=30))
    start = datetime(2026, 9, 4, 5, 30, tzinfo=tzinfo)  # 00:00 UTC
    end = datetime(2026, 9, 5, 5, 30, tzinfo=tzinfo)

    DahuaAdapter().search_recordings(dahua_client, ["1"], start, end)

    find = [
        r for r in dahua_server.calls_to(MEDIA_FILE_FIND) if r.query.get("action") == "findFile"
    ]
    assert find[-1].query["condition.StartTime"] == "2026-09-04 00:00:00"
    assert find[-1].query["condition.EndTime"] == "2026-09-05 00:00:00"


def test_a_naive_search_window_is_read_as_utc(dahua_server, dahua_client):
    """A datetime with no zone must not be reinterpreted as host local time."""
    DahuaAdapter().search_recordings(
        dahua_client, ["1"], datetime(2026, 9, 4, 0, 0), datetime(2026, 9, 5, 0, 0)
    )

    find = [
        r for r in dahua_server.calls_to(MEDIA_FILE_FIND) if r.query.get("action") == "findFile"
    ]
    assert find[-1].query["condition.StartTime"] == "2026-09-04 00:00:00"


def test_both_families_query_the_same_instant_the_same_way(
    dahua_server, dahua_client, hikvision_server, hik_client
):
    """The two adapters must not disagree about what window was searched."""
    tzinfo = timezone(timedelta(hours=5, minutes=30))
    start = datetime(2026, 9, 4, 5, 30, tzinfo=tzinfo)
    end = datetime(2026, 9, 5, 5, 30, tzinfo=tzinfo)

    DahuaAdapter().search_recordings(dahua_client, ["1"], start, end)
    HikvisionAdapter().search_recordings(hik_client, ["1"], start, end)

    dahua_query = [
        r for r in dahua_server.calls_to(MEDIA_FILE_FIND) if r.query.get("action") == "findFile"
    ][-1].query["condition.StartTime"]
    hikvision_body = hikvision_server.calls_to("/ISAPI/ContentMgmt/search")[-1].text

    assert dahua_query == "2026-09-04 00:00:00"
    assert "<startTime>2026-09-04T00:00:00Z</startTime>" in hikvision_body


def test_the_finder_handle_is_released_after_a_successful_search(
    dahua_server, dahua_client
):
    search(dahua_client)

    assert unique_actions(dahua_server) == [
        "factory.create",
        "findFile",
        "findNextFile",
        "close",
        "destroy",
    ]


def test_the_finder_handle_is_released_when_the_search_errors(
    dahua_server, client_factory
):
    """A 500 mid-search still leaves the finder allocated on the device."""
    dahua_server.fail_find_next = True
    client = client_factory(dahua_server)

    index = search(client)

    assert index.recordings == []
    actions = unique_actions(dahua_server)
    assert "close" in actions
    assert "destroy" in actions
    assert actions.index("close") > actions.index("findNextFile")
    closed = [r for r in dahua_server.calls_to(MEDIA_FILE_FIND) if r.query.get("action") == "close"]
    assert closed[-1].query["object"] == mock.FINDER_HANDLE


def test_a_refused_search_is_reported_as_a_warning_not_as_an_empty_index(
    dahua_server, client_factory
):
    """"No footage exists" and "we were not told" must never look alike.

    An empty index with no warning invites exactly the conclusion a forensic
    record must not support, so a refused findNextFile has to leave a trace.
    """
    dahua_server.fail_find_next = True
    client = client_factory(dahua_server)

    index = search(client)

    assert index.recordings == []
    assert len(index.warnings) == 1
    warning = index.warnings[0]
    assert "Channel 1" in warning
    assert "refused findNextFile" in warning
    assert "absence of footage cannot be inferred" in warning


def test_a_refused_findfile_is_reported_per_channel(dahua_server, client_factory):
    """The channel is named, because only that channel's index went unread."""
    dahua_server.fail_find_file = True
    client = client_factory(dahua_server)

    index = search(client, channels=("1", "2"))

    assert index.recordings == []
    assert len(index.warnings) == 2
    assert "Channel 1: findFile was refused" in index.warnings[0]
    assert "Channel 2: findFile was refused" in index.warnings[1]
    assert all("never read" in warning for warning in index.warnings)


def test_a_partial_read_does_not_discard_what_was_already_indexed(
    dahua_server, client_factory
):
    """A refusal mid-pagination keeps the segments already returned, with a warning."""
    dahua_server.full_pages = True
    dahua_server.fail_find_next_after = 1
    client = client_factory(dahua_server)

    index = search(client, max_results=200)

    # The first page of 100 survives; the second was refused.
    assert len(index.recordings) == 100
    assert any("only partially read" in warning for warning in index.warnings)


def test_pagination_stops_at_max_results_and_flags_truncation(
    dahua_server, client_factory
):
    """A capped result set must never be presented as a complete index."""
    dahua_server.full_pages = True
    client = client_factory(dahua_server)

    index = search(client, max_results=100)

    assert len(index.recordings) == 100
    assert index.truncated is True
    assert index.warnings == []


def test_a_recorder_that_cannot_allocate_a_finder_is_reported(
    dahua_server, client_factory
):
    dahua_server.disabled_paths = {MEDIA_FILE_FIND}
    client = client_factory(dahua_server)

    index = search(client)

    assert index.recordings == []
    assert any("finder object" in warning for warning in index.warnings)


def test_search_defaults_to_channel_one_when_none_is_named(dahua_server, dahua_client):
    index = search(dahua_client, channels=())

    assert index.channels_searched == ["1"]
    find = [r for r in dahua_server.calls_to(MEDIA_FILE_FIND) if r.query.get("action") == "findFile"]
    assert find[-1].query["condition.Channel"] == "1"


def test_a_single_indexed_file_is_handled(dahua_server, client_factory):
    dahua_server.single_item = True
    client = client_factory(dahua_server)

    index = search(client)

    assert len(index.recordings) == 1
    assert index.gaps("1") == []


def test_multiple_channels_are_searched_independently(dahua_server, dahua_client):
    index = search(dahua_client, channels=("1", "2"))

    assert index.channels_searched == ["1", "2"]
    assert len(index.recordings) == 6
    creates = [
        r for r in dahua_server.calls_to(MEDIA_FILE_FIND)
        if r.query.get("action") == "factory.create"
    ]
    # One finder per channel, each opened and released in turn.
    assert len({r.query.get("action") for r in dahua_server.calls_to(MEDIA_FILE_FIND)}) == 5
    assert len(creates) >= 2


@pytest.mark.parametrize("index", [0, 1, 2])
def test_indexed_file_paths_round_trip_for_acquisition(dahua_client, dahua_server, index):
    """The on-device path is the only locator Dahua acquisition can use."""
    recordings = search(dahua_client).recordings

    assert recordings[index].file_path == dahua_server.file_path(index)
    assert recordings[index].file_path.startswith("/mnt/dvr/")

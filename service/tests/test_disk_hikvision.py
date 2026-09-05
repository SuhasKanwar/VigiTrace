"""Reader, carve, and recovery tests for the HIKVISION on-disk format.

The synthetic image builder in ``tests/disk/hikvision_image.py`` deliberately
writes every offset from its own literals instead of importing
``disk.hikvision.layout``: if the two ever disagree about where a field lives,
a test here fails instead of the mistake cancelling itself out. Several tests
below lean on that separation directly (parity checks, poking the raw bytes at
a layout-derived offset) rather than only building images through the public
API.
"""

import os
import struct
from datetime import datetime, timezone

import pytest

from disk.hikvision import layout as L
from disk.hikvision.carve import (
    carve_block,
    export_header,
    ffprobe_available,
    find_cut_points,
    verify_with_decoder,
    write_segment,
)
from disk.hikvision.reader import DiskFormatError, HikvisionVolume
from disk.hikvision.recovery import find_timeline_gaps, scan_unreferenced_blocks
from tests.disk.hikvision_image import BTREE_AT, DATA_AREA_AT, ENTRIES_PER_PAGE, HikvisionImageBuilder
from tests.disk.video import build_program_stream_map, ffmpeg_available, make_program_stream

BASE_TIME = 1_700_000_000
BLOCK_SIZE = 1 << 18  # small enough to keep the suite fast; the field itself is what's under test


def _synthetic_video(pack_count: int = 3) -> bytes:
    """Bytes with genuine pack-header/PSM magic but no real H.264 payload.

    This drives the byte-pattern logic in carve/recovery (pack counting,
    keyframe-boundary detection, IDR-table recovery) without paying for an
    ffmpeg encode. Only the decode-oracle test needs a real decodable stream.
    """
    psm = build_program_stream_map()
    chunk = L.PS_PACK_HEADER + b"\x00" * 8 + psm
    return chunk * pack_count


class TestLayoutParity:
    def test_entries_per_page_matches_the_independently_derived_constant(self):
        """The builder computes this from PAGE_SIZE/ENTRY_SIZE literals of its own.

        Both sides landing on 83 is the whole point of not sharing a constants
        module: it is real agreement, not one offset masking another.
        """
        assert ENTRIES_PER_PAGE == L.MAX_ENTRIES_PER_PAGE == 83


class TestMasterSector:
    def test_header_fields_round_trip(self, tmp_path):
        image_path = tmp_path / "volume.img"
        HikvisionImageBuilder(block_size=BLOCK_SIZE, block_count=3, init_time=BASE_TIME).write(
            str(image_path)
        )

        with HikvisionVolume(str(image_path)) as volume:
            master = volume.master

        assert master.version == "HIK.2011.03.08"
        assert master.data_block_size == BLOCK_SIZE
        assert master.data_block_count == 3
        assert master.data_area_offset == DATA_AREA_AT
        assert master.total_capacity_bytes == DATA_AREA_AT + 3 * BLOCK_SIZE
        assert master.initialised_at == datetime.fromtimestamp(BASE_TIME, tz=timezone.utc)

    def test_corrupted_signature_names_the_expected_magic(self, tmp_path):
        image = bytearray(HikvisionImageBuilder(block_size=BLOCK_SIZE, block_count=1).build())
        image[L.SIGNATURE_OFFSET] ^= 0xFF  # flip a byte inside the 18-byte signature
        image_path = tmp_path / "corrupt.img"
        image_path.write_bytes(image)

        with pytest.raises(DiskFormatError) as excinfo:
            HikvisionVolume(str(image_path))

        assert "HIKVISION@HANGZHOU" in excinfo.value.detail

    def test_unknown_format_version_is_refused_not_guessed(self, tmp_path):
        """A version this parser has never seen must not be parsed on a guess.

        Other Hikvision generations exist in the wild and are undocumented;
        silently applying the known layout to one would produce confident,
        wrong evidence rather than an honest failure.
        """
        image_path = tmp_path / "future.img"
        HikvisionImageBuilder(
            block_size=BLOCK_SIZE, block_count=1, version=b"HIK.2019.99.99"
        ).write(str(image_path))

        with pytest.raises(DiskFormatError) as excinfo:
            HikvisionVolume(str(image_path))

        assert "HIK.2019.99.99" in excinfo.value.message
        assert "refused rather than guessed" in excinfo.value.detail


class TestChannelDecoding:
    """Channel is the one big-endian field in the entry structure.

    256 (0x0100) and 513 (0x0201) are chosen because misreading either as
    little-endian yields a different, plausible-looking channel number (1 and
    258 respectively) rather than an obvious garbage value - exactly the
    silent-wrong-camera failure a byte-order bug would produce.
    """

    @pytest.mark.parametrize("channel", [256, 513])
    def test_channel_round_trips_big_endian(self, tmp_path, channel):
        image_path = tmp_path / "be.img"
        builder = HikvisionImageBuilder(block_size=BLOCK_SIZE, block_count=1, init_time=BASE_TIME)
        builder.add_recording(channel=channel, start=BASE_TIME, end=BASE_TIME + 60, payload=b"")
        builder.write(str(image_path))

        with HikvisionVolume(str(image_path)) as volume:
            entries = volume.entries()

        assert len(entries) == 1
        assert entries[0].channel == channel


class TestMultiPageIndex:
    def test_page_chain_is_fully_walked(self, tmp_path):
        count = ENTRIES_PER_PAGE + 7  # forces a second page in the chain
        builder = HikvisionImageBuilder(block_size=1 << 12, block_count=count, init_time=BASE_TIME)
        for channel in range(1, count + 1):
            start = BASE_TIME + channel * 100
            builder.add_recording(channel=channel, start=start, end=start + 30, payload=b"")
        image_path = tmp_path / "multipage.img"
        builder.write(str(image_path))

        with HikvisionVolume(str(image_path)) as volume:
            entries = volume.entries()

        assert len(entries) == count
        assert {e.channel for e in entries} == set(range(1, count + 1))

        by_page = {0: 0, 1: 0}
        for entry in entries:
            by_page[entry.page_index] = by_page.get(entry.page_index, 0) + 1
        assert by_page[0] == ENTRIES_PER_PAGE
        assert by_page[1] == count - ENTRIES_PER_PAGE
        assert max(e.page_index for e in entries) == 1


class TestPageChainLoopGuard:
    def test_self_referential_next_page_terminates(self, tmp_path):
        """A page whose next-page pointer is itself must not spin the reader.

        The chain is built normally and then the raw next-page field is poked
        to point back at the page it belongs to, which is what a corrupted or
        deliberately looped index looks like on disk.
        """
        builder = HikvisionImageBuilder(block_size=BLOCK_SIZE, block_count=1, init_time=BASE_TIME)
        builder.add_recording(channel=1, start=BASE_TIME, end=BASE_TIME + 10, payload=b"")
        image = bytearray(builder.build())

        first_page_at = BTREE_AT + 0x1000
        struct.pack_into("<Q", image, first_page_at + L.PAGE_NEXT_PAGE_OFFSET, first_page_at)

        image_path = tmp_path / "loop.img"
        image_path.write_bytes(image)

        with HikvisionVolume(str(image_path)) as volume:
            entries = volume.entries()  # must return promptly, not spin forever

        assert len(entries) == 1
        assert entries[0].channel == 1


class TestUnfinalisedEntries:
    def test_sentinel_is_flagged_start_is_none_and_entry_is_kept(self, tmp_path):
        builder = HikvisionImageBuilder(block_size=BLOCK_SIZE, block_count=1, init_time=BASE_TIME)
        builder.add_recording(
            channel=4, start=BASE_TIME, end=BASE_TIME + 90, payload=b"", unfinalised=True
        )
        image_path = tmp_path / "unfinalised.img"
        builder.write(str(image_path))

        with HikvisionVolume(str(image_path)) as volume:
            entries = volume.entries()

        assert len(entries) == 1  # never dropped for having a placeholder timestamp
        entry = entries[0]
        assert entry.unfinalised is True
        assert entry.start is None
        assert entry.raw_start == L.UNFINALISED_TIME
        assert entry.end == datetime.fromtimestamp(BASE_TIME + 90, tz=timezone.utc)
        assert entry.duration_seconds is None


class TestLooksLikeHikvision:
    def test_true_for_a_real_image(self, tmp_path):
        image_path = tmp_path / "real.img"
        HikvisionImageBuilder(block_size=BLOCK_SIZE, block_count=1).write(str(image_path))

        assert HikvisionVolume.looks_like_hikvision(str(image_path)) is True

    def test_false_for_random_bytes(self, tmp_path):
        image_path = tmp_path / "random.bin"
        image_path.write_bytes(os.urandom(4096))

        assert HikvisionVolume.looks_like_hikvision(str(image_path)) is False


class TestReadOnlyAccess:
    def test_bytes_and_mtime_survive_a_full_read(self, tmp_path):
        """Nothing in the reader/recovery path may write back to the source.

        The image is evidence: even a full walk of the index, every data
        block, and an unreferenced-block sweep must leave the acquired bytes
        and their mtime exactly as they were.
        """
        builder = HikvisionImageBuilder(block_size=BLOCK_SIZE, block_count=2, init_time=BASE_TIME)
        builder.add_recording(channel=1, start=BASE_TIME, end=BASE_TIME + 60, payload=_synthetic_video())
        builder.add_recording(
            channel=2, start=BASE_TIME + 500, end=BASE_TIME + 560,
            payload=_synthetic_video(), orphaned=True,
        )
        image_path = tmp_path / "readonly.img"
        builder.write(str(image_path))

        before_bytes = image_path.read_bytes()
        before_mtime_ns = os.stat(image_path).st_mtime_ns

        with HikvisionVolume(str(image_path)) as volume:
            entries = volume.entries()
            for entry in entries:
                bytes(volume.read_block(entry.data_offset))
            scan_unreferenced_blocks(volume, entries)

        assert image_path.read_bytes() == before_bytes
        assert os.stat(image_path).st_mtime_ns == before_mtime_ns


class TestFindCutPoints:
    def test_pack_header_followed_by_map_is_keyframe_aligned(self):
        data = (
            b"junk"
            + L.PS_PACK_HEADER + b"\x00" * 6 + L.PS_PROGRAM_STREAM_MAP + b"rest"
            + b"\xaa" * 40
            + L.PS_PACK_HEADER + b"\x00" * 60
        )

        points = find_cut_points(data)

        assert len(points) == 2
        assert points[0][1] is True
        assert points[1][1] is False

    @pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg is not installed")
    def test_stream_without_maps_has_no_aligned_cuts(self):
        """ffmpeg's own PS muxer emits no program stream map at all.

        Every cut point found in such a stream must come back unaligned,
        which is the fixture that proves the aligned/unaligned distinction is
        not a tautology of the test data.
        """
        stream = make_program_stream(seconds=1, width=64, height=64, fps=5, with_maps=False)

        points = find_cut_points(stream)

        assert points
        assert not any(aligned for _, aligned in points)


class TestCarveBlock:
    def test_stops_before_the_idr_table(self, tmp_path):
        builder = HikvisionImageBuilder(block_size=BLOCK_SIZE, block_count=1, init_time=BASE_TIME)
        builder.add_recording(channel=5, start=BASE_TIME, end=BASE_TIME + 30, payload=_synthetic_video())
        image_path = tmp_path / "carve.img"
        builder.write(str(image_path))

        with HikvisionVolume(str(image_path)) as volume:
            entry = volume.entries()[0]
            segment = carve_block(
                volume.read_block(entry.data_offset), channel=entry.channel, block_offset=entry.data_offset
            )

        assert segment is not None
        assert b"OFNI" not in segment.data

    def test_garbage_bytes_yield_no_segment(self):
        """No pack header anywhere means nothing to carve, not a bogus guess."""
        assert carve_block(bytes(4096), channel=1, block_offset=0) is None


class TestExportHeader:
    def test_is_forty_bytes_starting_imkh(self):
        header = export_header()

        assert len(header) == 40
        assert header.startswith(b"IMKH")


class TestDecodeOracle:
    @pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg is not installed")
    @pytest.mark.skipif(not ffprobe_available(), reason="ffprobe is not installed")
    def test_a_carved_indexed_block_actually_decodes(self, tmp_path):
        """ffprobe is independent corroboration, not self-confirmation.

        This is the only test that hands carved output to a real decoder end
        to end; it must not be weakened just because ffmpeg/ffprobe happen to
        be present.
        """
        video = make_program_stream(seconds=2, width=160, height=120, fps=10, with_maps=True)
        builder = HikvisionImageBuilder(block_size=BLOCK_SIZE, block_count=1, init_time=BASE_TIME)
        builder.add_recording(channel=9, start=BASE_TIME, end=BASE_TIME + 2, payload=video)
        image_path = tmp_path / "decode.img"
        builder.write(str(image_path))

        with HikvisionVolume(str(image_path)) as volume:
            entry = volume.entries()[0]
            segment = carve_block(
                volume.read_block(entry.data_offset), channel=entry.channel, block_offset=entry.data_offset
            )

        assert segment is not None
        out_path = str(tmp_path / "carved.ps")
        write_segment(segment, out_path)

        verdict = verify_with_decoder(out_path)

        assert verdict.decoded is True
        assert verdict.codec == "h264"
        assert verdict.frames is not None and verdict.frames > 0


class TestUnreferencedBlockScan:
    def test_orphaned_recording_is_found_with_strong_confidence(self, tmp_path):
        builder = HikvisionImageBuilder(block_size=BLOCK_SIZE, block_count=2, init_time=BASE_TIME)
        builder.add_recording(channel=1, start=BASE_TIME, end=BASE_TIME + 60, payload=_synthetic_video())
        builder.add_recording(
            channel=7, start=BASE_TIME + 500, end=BASE_TIME + 560,
            payload=_synthetic_video(), orphaned=True,
        )
        image_path = tmp_path / "orphan.img"
        builder.write(str(image_path))

        with HikvisionVolume(str(image_path)) as volume:
            entries = volume.entries()
            indexed_offsets = {e.data_offset for e in entries}
            unreferenced = scan_unreferenced_blocks(volume, entries)

        assert len(entries) == 1  # the orphaned recording never made it into the index
        assert len(unreferenced) == 1
        block = unreferenced[0]
        assert block.data_offset not in indexed_offsets
        assert block.idr_channel == 7
        assert block.confidence == "STRONG"

    def test_a_block_with_no_video_is_not_reported(self, tmp_path):
        # block_count=2 with one recording leaves the second data block all
        # zero: a real gap in the data area, not footage the index forgot.
        builder = HikvisionImageBuilder(block_size=BLOCK_SIZE, block_count=2, init_time=BASE_TIME)
        builder.add_recording(channel=1, start=BASE_TIME, end=BASE_TIME + 60, payload=_synthetic_video())
        image_path = tmp_path / "empty_block.img"
        builder.write(str(image_path))

        with HikvisionVolume(str(image_path)) as volume:
            unreferenced = scan_unreferenced_blocks(volume)

        assert unreferenced == []


class TestTimelineGaps:
    def test_gap_is_found_adjacent_pairs_are_not_and_unfinalised_is_excluded(self, tmp_path):
        builder = HikvisionImageBuilder(block_size=BLOCK_SIZE, block_count=4, init_time=BASE_TIME)
        builder.add_recording(channel=1, start=BASE_TIME, end=BASE_TIME + 60, payload=b"")
        builder.add_recording(channel=1, start=BASE_TIME + 300, end=BASE_TIME + 360, payload=b"")
        builder.add_recording(  # starts exactly where the previous one ends: no gap
            channel=1, start=BASE_TIME + 360, end=BASE_TIME + 420, payload=b""
        )
        builder.add_recording(  # unfinalised: excluded from gap detection entirely
            channel=1, start=BASE_TIME + 1000, end=BASE_TIME + 1060, payload=b"", unfinalised=True
        )
        image_path = tmp_path / "gaps.img"
        builder.write(str(image_path))

        with HikvisionVolume(str(image_path)) as volume:
            gaps = find_timeline_gaps(volume.entries())

        assert len(gaps) == 1
        gap = gaps[0]
        assert gap.channel == 1
        assert gap.duration_seconds == 240.0
        assert gap.start == datetime.fromtimestamp(BASE_TIME + 60, tz=timezone.utc)
        assert gap.end == datetime.fromtimestamp(BASE_TIME + 300, tz=timezone.utc)

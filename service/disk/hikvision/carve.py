"""Extract playable video out of HIKVISION data blocks.

Three rules here come from published analysis of real recorder output, and
each exists because ignoring it produces silently wrong results rather than an
error:

1. **Demux as MPEG-PS, never as raw H.264.** A pack header's 0xBA byte masks as
   NAL type 26 to an Annex-B parser, which then floods "Failed to parse header
   of NALU", drops timestamps, and loses audio entirely.
2. **Cut at a pack header that is immediately followed by a program stream
   map.** That point is simultaneously a pack boundary, a PSM, and a keyframe,
   because SPS/PPS are re-emitted with every map. Cutting mid-GOP yields
   "non-existing PPS 0 referenced" and unplayable output.
3. **Prepend the 40-byte IMKH export header.** ffmpeg sniffs only the first six
   bytes; without that magic it maps stream type 0x91 to something other than
   mu-law and the audio track is silently dropped.
"""

import hashlib
import os
import shutil
import subprocess
from dataclasses import dataclass, field

from disk.hikvision import layout as L


@dataclass
class CarvedSegment:
    """One extracted run of program stream, with its integrity material."""

    channel: int
    block_offset: int
    start_in_block: int
    length: int
    data: bytes
    sha256: str
    #: True when the cut landed on a pack header followed by a program stream
    #: map, which is the only boundary guaranteed to also be a keyframe.
    keyframe_aligned: bool


@dataclass
class DecodeVerdict:
    """What an external decoder made of a carved segment.

    This is the part of the pipeline that does not depend on our reading of the
    format: ffmpeg has its own implementation, so a successful decode is
    independent corroboration rather than self-confirmation.
    """

    decoded: bool
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    frames: int | None = None
    reason: str | None = None
    warnings: list[str] = field(default_factory=list)


def export_header() -> bytes:
    """The 40-byte IMKH wrapper an exported Hikvision file carries."""
    return L.EXPORT_MAGIC + b"\x00" * (L.EXPORT_HEADER_SIZE - len(L.EXPORT_MAGIC))


def find_cut_points(data: bytes | memoryview) -> list[tuple[int, bool]]:
    """Locate every pack header, flagging those a program stream map follows.

    Returns ``(offset, keyframe_aligned)`` in file order. Plain pack headers are
    kept because some firmware emits few maps; the caller decides whether to
    accept a non-aligned cut.
    """
    payload = bytes(data)
    points: list[tuple[int, bool]] = []
    cursor = 0
    while True:
        cursor = payload.find(L.PS_PACK_HEADER, cursor)
        if cursor < 0:
            break
        window = payload[cursor : cursor + 64]
        points.append((cursor, L.PS_PROGRAM_STREAM_MAP in window))
        cursor += len(L.PS_PACK_HEADER)
    return points


def carve_block(
    block: bytes | memoryview,
    *,
    channel: int,
    block_offset: int,
    require_keyframe: bool = True,
) -> CarvedSegment | None:
    """Carve the largest playable run out of one data block.

    Starts at the first acceptable boundary and runs to the end of the video
    region, stopping before the IDR table that grows down from the block's tail.
    """
    payload = bytes(block)
    points = find_cut_points(payload)
    if not points:
        return None

    aligned = [offset for offset, is_aligned in points if is_aligned]
    if require_keyframe and aligned:
        start = aligned[0]
        keyframe_aligned = True
    elif require_keyframe and not aligned:
        # No map anywhere: rather than cut blind, fall back to the first pack
        # header and say so, so the caller can grade the artifact honestly.
        start = points[0][0]
        keyframe_aligned = False
    else:
        start = points[0][0]
        keyframe_aligned = points[0][1]

    end = _video_region_end(payload)
    if end <= start:
        return None

    data = payload[start:end]
    return CarvedSegment(
        channel=channel,
        block_offset=block_offset,
        start_in_block=start,
        length=len(data),
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        keyframe_aligned=keyframe_aligned,
    )


def _video_region_end(payload: bytes) -> int:
    """Where the video stops and the block's IDR table begins.

    The table grows downward from the end of the block, so the first OFNI
    record encountered from the tail marks the boundary. Carving past it would
    append index structures to the video and confuse the decoder.
    """
    lowest = len(payload)
    cursor = payload.rfind(L.IDR_SIGNATURE)
    while cursor > 0:
        lowest = min(lowest, cursor)
        cursor = payload.rfind(L.IDR_SIGNATURE, 0, cursor)
    return lowest


def write_segment(segment: CarvedSegment, destination: str, *, with_export_header: bool = True) -> str:
    """Write a carved segment out, wrapped so a decoder reads it correctly."""
    os.makedirs(os.path.dirname(destination) or ".", exist_ok=True)
    with open(destination, "wb") as handle:
        if with_export_header:
            handle.write(export_header())
        handle.write(segment.data)
    return destination


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def verify_with_decoder(path: str, *, timeout: int = 60) -> DecodeVerdict:
    """Ask ffprobe whether the carved file actually decodes.

    A carve that parses cleanly but will not decode is not recovered evidence,
    so this is treated as part of the extraction rather than as an optional
    extra. ffprobe's own exit status is not trusted alone: it reports success on
    files from which it recovered almost nothing, so the frame count is read and
    returned for the caller to judge.
    """
    if not ffprobe_available():
        return DecodeVerdict(False, reason="ffprobe is not installed, so the carve could not be verified.")

    try:
        probe = subprocess.run(
            [
                "ffprobe", "-hide_banner", "-v", "error",
                # Force the program-stream demuxer: sniffing can pick the raw
                # H.264 parser and then quietly produce garbage.
                "-f", "mpeg",
                "-count_frames",
                "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,width,height,nb_read_frames",
                "-of", "default=noprint_wrappers=1",
                path,
            ],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return DecodeVerdict(False, reason=f"Decoder did not finish within {timeout}s.")

    if probe.returncode != 0:
        return DecodeVerdict(False, reason=(probe.stderr or "ffprobe failed").strip()[:300])

    fields: dict[str, str] = {}
    for line in probe.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            fields[key.strip()] = value.strip()

    frames = fields.get("nb_read_frames")
    frame_count = int(frames) if frames and frames.isdigit() else None
    if not fields.get("codec_name") or not frame_count:
        return DecodeVerdict(
            False,
            codec=fields.get("codec_name"),
            reason="Decoder opened the file but read no video frames from it.",
        )

    warnings: list[str] = []
    if probe.stderr.strip():
        warnings = [line.strip() for line in probe.stderr.strip().splitlines()[:5]]

    return DecodeVerdict(
        decoded=True,
        codec=fields.get("codec_name"),
        width=int(fields["width"]) if fields.get("width", "").isdigit() else None,
        height=int(fields["height"]) if fields.get("height", "").isdigit() else None,
        frames=frame_count,
        warnings=warnings,
    )

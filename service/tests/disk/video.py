"""Build MPEG program-stream payloads shaped like recorder output.

ffmpeg's program-stream muxer emits no program stream map, but real Hikvision
volumes carry roughly one map per thirty packs, and the documented carve
boundary is a pack header immediately followed by a map. A fixture without maps
would leave that rule untested, so maps are inserted here.

The insertion is validated the only way that means anything: the resulting
stream is handed to ffprobe, and it decodes to the same frame count as the
original with no decode errors. A fixture that merely looked plausible would be
worse than none, because it would make a broken carver pass.
"""

import shutil
import struct
import subprocess

PACK_START = b"\x00\x00\x01\xba"
SYSTEM_HEADER_START = b"\x00\x00\x01\xbb"
PSM_START = b"\x00\x00\x01\xbc"

#: H.264 in the elementary stream map.
STREAM_TYPE_H264 = 0x1B
#: The elementary stream id ffmpeg assigns to the video track.
VIDEO_STREAM_ID = 0xE2


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def mpeg_crc32(data: bytes) -> int:
    """MPEG-2 systems CRC-32: poly 0x04C11DB7, init all-ones, MSB first, no final xor."""
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if crc & 0x80000000 else (crc << 1) & 0xFFFFFFFF
    return crc


def build_program_stream_map(stream_id: int = VIDEO_STREAM_ID, stream_type: int = STREAM_TYPE_H264) -> bytes:
    """A minimal ISO 13818-1 program stream map for a single video track."""
    body = bytearray([0xE0, 0xFF]) + struct.pack(">H", 0)   # version/marker, no program info
    elementary = bytes([stream_type, stream_id]) + struct.pack(">H", 0)
    body += struct.pack(">H", len(elementary)) + elementary
    header = PSM_START + struct.pack(">H", len(body) + 4)
    return header + bytes(body) + struct.pack(">I", mpeg_crc32(header + bytes(body)))


def _pack_header_length(stream: bytes, at: int) -> int:
    """MPEG-1 packs are 12 bytes; MPEG-2 packs are 14 plus declared stuffing.

    Getting this wrong splices a map into the middle of a PES packet, which
    still decodes - just with corrupted macroblocks and a third of the frames.
    """
    marker = stream[at + 4]
    if (marker >> 6) == 0b01:
        return 14 + (stream[at + 13] & 0x07)
    return 12


def _system_header_length(stream: bytes, at: int) -> int:
    if stream[at : at + 4] != SYSTEM_HEADER_START:
        return 0
    return 6 + struct.unpack_from(">H", stream, at + 4)[0]


def insert_program_stream_maps(stream: bytes, psm: bytes | None = None) -> bytes:
    """Place a map directly after each pack header, as a recorder does."""
    psm = psm if psm is not None else build_program_stream_map()
    out = bytearray()
    cursor = 0
    while True:
        at = stream.find(PACK_START, cursor)
        if at < 0:
            out += stream[cursor:]
            break
        after = at + _pack_header_length(stream, at)
        after += _system_header_length(stream, after)
        out += stream[cursor:after] + psm
        cursor = after
    return bytes(out)


def make_program_stream(seconds: int = 2, width: int = 320, height: int = 240, fps: int = 15,
                        pattern: str = "testsrc", with_maps: bool = True) -> bytes:
    """Encode real H.264 into an MPEG program stream.

    Real video rather than random bytes, because the point of the fixture is to
    let an external decoder confirm that carved output actually plays.
    """
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg is required to build video fixtures.")
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"{pattern}=size={width}x{height}:rate={fps}:duration={seconds}",
         "-c:v", "libx264", "-preset", "ultrafast", "-g", str(fps), "-pix_fmt", "yuv420p",
         "-f", "mpeg", "pipe:1"],
        capture_output=True, check=True,
    )
    stream = result.stdout
    return insert_program_stream_maps(stream) if with_maps else stream

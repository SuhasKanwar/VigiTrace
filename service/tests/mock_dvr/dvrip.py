"""A mock XiongMai/Sofia recorder speaking DVRIP, as Godrej units do.

The frame layout and the ``sofia_hash`` password digest are re-implemented here
from the protocol description rather than imported from
``vendors.transports.dvrip``: a mock that borrowed the implementation under test
would agree with it even when both were wrong.
"""

import hashlib
import json
import socketserver
import struct
import threading
from typing import Any

#: 20-byte little-endian header: magic, version, 2 pad, session, sequence,
#: total packets, current packet, message id, payload length.
HEADER = struct.Struct("<BB2xIIBBHI")
HEADER_SIZE = 20
MAGIC = 0xFF

LOGIN_REQUEST = 1000
GET_INFO_REQUEST = 1020
TIME_QUERY_REQUEST = 1452

RET_OK = 100
RET_BAD_PASSWORD = 205

SESSION_ID = 1

SERIAL_NO = "4a2b1c9d8e7f6051"
HARDWARE = "HI3520D_A2"
SOFTWARE_VERSION = "V4.02.R11.34500006.10010.140000.0000000"
BUILD_TIME = "2018-05-08 15:26:37"
VIDEO_IN_CHANNELS = 4
DIGITAL_CHANNELS = 0

DEVICE_TIME = "2026-09-04 10:00:00"

#: XiongMai reports partition sizes in megabytes, encoded as hex strings.
TOTAL_SPACE_MB = 1904640
REMAIN_SPACE_MB = 102400
TOTAL_SPACE_HEX = f"0x{TOTAL_SPACE_MB:08X}"
REMAIN_SPACE_HEX = f"0x{REMAIN_SPACE_MB:08X}"


def sofia_hash(password: str) -> str:
    """XiongMai's 8-character password digest, implemented independently.

    Pairs of MD5 bytes are summed and folded into a 62-character alphabet.
    """
    digest = hashlib.md5(password.encode("utf-8")).digest()
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    out = ""
    for index in range(0, 16, 2):
        out += alphabet[(digest[index] + digest[index + 1]) % 62]
    return out


class DvripHandler(socketserver.BaseRequestHandler):
    """One DVRIP connection; the client keeps it open for the whole session."""

    server: "DvripServer"

    def handle(self) -> None:
        while True:
            header = self._read_exactly(HEADER_SIZE)
            if header is None:
                return
            magic, _version, _session, _sequence, _total, _current, message_id, length = (
                HEADER.unpack(header)
            )
            if magic != MAGIC:
                return
            payload = self._read_exactly(length) if length else b""
            if payload is None:
                return
            text = payload.rstrip(b"\x00").decode("utf-8", "replace").strip()
            try:
                request = json.loads(text) if text else {}
            except json.JSONDecodeError:
                request = {}
            reply_id, response = self.server.dispatch(message_id, request)
            self._send(reply_id, response)

    def _read_exactly(self, count: int) -> bytes | None:
        chunks: list[bytes] = []
        outstanding = count
        while outstanding > 0:
            try:
                chunk = self.request.recv(outstanding)
            except OSError:
                # The client hangs up whenever it decides a frame is malformed,
                # which is a normal end of conversation here, not a fault.
                return None
            if not chunk:
                return None
            chunks.append(chunk)
            outstanding -= len(chunk)
        return b"".join(chunks)

    def _send(self, message_id: int, payload: dict[str, Any]) -> None:
        """Frame and write one reply; a hung-up client is not an error."""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\x0a\x00"
        magic = 0x00 if self.server.corrupt_magic else MAGIC
        # An implausible declared length is how a non-DVRIP service on 34567
        # tends to present itself, so the transport must reject it.
        declared = 8 * 1024 * 1024 if self.server.oversized_length else len(body)
        header = HEADER.pack(
            magic, 0, self.server.session_for_reply(), 0, 0, 0, message_id, declared
        )
        try:
            self.request.sendall(header + body)
        except OSError:
            return


class DvripServer(socketserver.ThreadingTCPServer):
    """A XiongMai-lineage recorder on an ephemeral port."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, username: str = "admin", password: str = "Vigi#Trace1") -> None:
        super().__init__(("127.0.0.1", 0), DvripHandler)
        self.username = username
        self.password = password
        self.logged_in = False
        self.messages: list[tuple[int, dict[str, Any]]] = []
        #: Recorded so a test can prove the client sent the Sofia digest of the
        #: password rather than the password itself.
        self.passwords_seen: list[str] = []
        self.device_time = DEVICE_TIME
        #: Real firmware reports partition sizes as hex strings; the decimal
        #: form exists so both parsing paths can be exercised.
        self.hex_space = True
        #: Some firmware repeats the space figures at the disk level as well as
        #: inside each partition.
        self.duplicate_disk_level_space = False
        #: Other firmware reports one flat disk record with no Partition block.
        self.partitionless_disk = False
        #: Fault injection for the frame parser.
        self.corrupt_magic = False
        self.oversized_length = False
        self._thread: threading.Thread | None = None

    @property
    def host(self) -> str:
        return self.server_address[0]

    @property
    def port(self) -> int:
        return self.server_address[1]

    def start(self) -> "DvripServer":
        self._thread = threading.Thread(
            target=self.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def session_for_reply(self) -> int:
        return SESSION_ID if self.logged_in else 0

    def dispatch(self, message_id: int, request: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        self.messages.append((message_id, request))

        if message_id == LOGIN_REQUEST:
            return LOGIN_REQUEST + 1, self._login(request)
        if message_id == GET_INFO_REQUEST:
            return GET_INFO_REQUEST + 1, self._get_info(request)
        if message_id == TIME_QUERY_REQUEST:
            return TIME_QUERY_REQUEST + 1, {
                "Name": "OPTimeQuery",
                "OPTimeQuery": self.device_time,
                "Ret": RET_OK,
                "SessionID": f"0x{SESSION_ID:08X}",
            }
        return message_id + 1, {"Ret": 404, "SessionID": "0x00000000"}

    def _login(self, request: dict[str, Any]) -> dict[str, Any]:
        offered = str(request.get("PassWord", ""))
        self.passwords_seen.append(offered)
        if request.get("UserName") != self.username or offered != sofia_hash(self.password):
            self.logged_in = False
            return {"Ret": RET_BAD_PASSWORD, "SessionID": "0x00000000"}
        self.logged_in = True
        return {
            "AliveInterval": 21,
            "ChannelNum": VIDEO_IN_CHANNELS,
            "DeviceType ": "DVR",
            "ExtraChannel": 0,
            "Ret": RET_OK,
            "SessionID": f"0x{SESSION_ID:08X}",
        }

    def _get_info(self, request: dict[str, Any]) -> dict[str, Any]:
        name = request.get("Name")
        if name == "SystemInfo":
            return {
                "Name": "SystemInfo",
                "Ret": RET_OK,
                "SessionID": f"0x{SESSION_ID:08X}",
                "SystemInfo": {
                    "AlarmInChannel": 4,
                    "AlarmOutChannel": 1,
                    "AudioInChannel": 1,
                    "BuildTime": BUILD_TIME,
                    "CombineSwitch": 0,
                    "DeviceModel": "Godrej-Seethru",
                    "DeviceRunTime": "0x00004f2a",
                    "DigChannel": DIGITAL_CHANNELS,
                    "EncryptVersion": "Unknown",
                    "ExtraChannel": 0,
                    "HardWare": HARDWARE,
                    "HardWareVersion": "",
                    "SerialNo": SERIAL_NO,
                    "SoftWareVersion": SOFTWARE_VERSION,
                    "TalkInChannel": 1,
                    "TalkOutChannel": 1,
                    "UpdataTime": "",
                    "UpdataType": "0x00000000",
                    "VideoInChannel": VIDEO_IN_CHANNELS,
                    "VideoOutChannel": 1,
                },
            }
        if name == "StorageInfo":
            return {
                "Name": "StorageInfo",
                "Ret": RET_OK,
                "SessionID": f"0x{SESSION_ID:08X}",
                "StorageInfo": [[self._disk()]],
            }
        return {"Name": name, "Ret": 404, "SessionID": f"0x{SESSION_ID:08X}"}

    def _disk(self) -> dict[str, Any]:
        total = TOTAL_SPACE_HEX if self.hex_space else TOTAL_SPACE_MB
        remain = REMAIN_SPACE_HEX if self.hex_space else REMAIN_SPACE_MB
        partition = {
            "DirverType": "ReadWrite",
            "EndTime": "2026-09-04 10:00:00",
            "LogicSerialNo": "4a2b1c9d",
            "NewStartTime": "2026-09-01 08:00:00",
            "RemainSpace": remain,
            "StartTime": "2026-09-01 08:00:00",
            "Status": "Read&Write",
            "TotalSpace": total,
        }
        if self.partitionless_disk:
            return {
                "LogicSerialNo": "4a2b1c9d",
                "PartNumber": 1,
                "RemainSpace": remain,
                "Status": "Read&Write",
                "TotalSpace": total,
            }

        disk: dict[str, Any] = {
            "Partition": [partition],
            "PartNumber": 1,
            "SerialNo": "4a2b1c9d",
            "Status": "Read&Write",
        }
        if self.duplicate_disk_level_space:
            disk["TotalSpace"] = total
            disk["RemainSpace"] = remain
        return disk

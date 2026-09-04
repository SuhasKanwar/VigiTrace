"""DVRIP (XiongMai / "Sofia") transport, used by Godrej-badged recorders.

This protocol shares nothing with the Hikvision or Dahua HTTP stacks: it is a
binary-framed JSON exchange on TCP 34567, with a bespoke password hash. It is
implemented here rather than pulled from a dependency because the two PyPI
packages that speak it (``dvrip``, ``python-dvr``) are unmaintained and neither
is packaged for reuse.

Frame layout (20-byte header, little-endian, followed by a NUL-terminated JSON
payload)::

    0      u8   magic, always 0xFF
    1      u8   version, 0
    2-3         reserved
    4-7    u32  session id (0 until login succeeds)
    8-11   u32  sequence number
    12     u8   total packets
    13     u8   current packet
    14-15  u16  message id
    16-19  u32  payload length
"""

import hashlib
import json
import socket
import struct
from datetime import datetime, timezone

from models.common import ErrorCode, ProbeMethod
from models.device import RawArtifact
from vendors.transports.http_digest import TransportError

HEADER = struct.Struct("<BB2xIIBBHI")
HEADER_SIZE = 20
MAGIC = 0xFF

LOGIN_REQUEST = 1000
GET_INFO_REQUEST = 1020
TIME_QUERY_REQUEST = 1452

DEFAULT_PORT = 34567
#: Ret == 100 is the protocol's success code.
RET_OK = 100
_MAX_PAYLOAD = 4 * 1024 * 1024


def sofia_hash(password: str) -> str:
    """XiongMai's bespoke 8-character password digest.

    Folds the MD5 of the password pairwise into a 62-character alphabet. This
    is the vendor's scheme, not a security recommendation - it is required to
    speak the protocol at all.
    """
    digest = hashlib.md5(password.encode("utf-8")).digest()
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    return "".join(alphabet[(digest[i] + digest[i + 1]) % 62] for i in range(0, 16, 2))


def port_open(host: str, port: int = DEFAULT_PORT, timeout: float = 3.0) -> bool:
    """Cheap unauthenticated reachability check used for fingerprinting."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class DvripClient:
    """A DVRIP session against one recorder."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        username: str = "admin",
        password: str = "",
        timeout: float = 8.0,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self.session = 0
        self.sequence = 0
        self.artifacts: list[RawArtifact] = []
        self.attempted: list[str] = []
        self.succeeded: list[str] = []
        self._socket: socket.socket | None = None

    def __enter__(self) -> "DvripClient":
        self.connect()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def connect(self) -> None:
        try:
            self._socket = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self._socket.settimeout(self.timeout)
        except socket.timeout as exc:
            raise TransportError(
                ErrorCode.TIMEOUT, f"Timed out connecting to {self.host}:{self.port}.", str(exc)
            )
        except OSError as exc:
            raise TransportError(
                ErrorCode.UNREACHABLE,
                f"Could not open a DVRIP connection to {self.host}:{self.port}.",
                str(exc),
            )

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None

    def _send(self, message_id: int, payload: dict) -> dict:
        if self._socket is None:
            raise TransportError(ErrorCode.INTERNAL, "DVRIP client is not connected.")

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\x0a\x00"
        header = HEADER.pack(MAGIC, 0, self.session, self.sequence, 0, 0, message_id, len(body))
        try:
            self._socket.sendall(header + body)
        except OSError as exc:
            raise TransportError(ErrorCode.UNREACHABLE, "DVRIP send failed.", str(exc))

        self.sequence += 1
        return self._receive(message_id)

    def _receive(self, message_id: int) -> dict:
        raw_header = self._read_exactly(HEADER_SIZE)
        magic, _version, session, _sequence, _total, _current, _reply_id, length = HEADER.unpack(
            raw_header
        )
        if magic != MAGIC:
            raise TransportError(
                ErrorCode.PROTOCOL_ERROR,
                "Response did not carry a DVRIP frame header.",
                f"Expected magic 0x{MAGIC:02X}, received 0x{magic:02X}.",
            )
        if length > _MAX_PAYLOAD:
            raise TransportError(
                ErrorCode.PROTOCOL_ERROR,
                "DVRIP frame declared an implausible payload length.",
                f"{length} bytes for message {message_id}.",
            )
        if session:
            self.session = session

        body = self._read_exactly(length) if length else b""
        text = body.rstrip(b"\x00").decode("utf-8", "replace").strip()
        self.artifacts.append(
            RawArtifact(
                endpoint=f"dvrip:{message_id}",
                method=ProbeMethod.XIONGMAI_DVRIP,
                status_code=None,
                content_type="application/json",
                body=text,
                sha256=hashlib.sha256(text.encode("utf-8", "replace")).hexdigest(),
                retrieved_at=datetime.now(timezone.utc),
            )
        )
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise TransportError(
                ErrorCode.PROTOCOL_ERROR, "DVRIP payload was not valid JSON.", str(exc)
            )

    def _read_exactly(self, count: int) -> bytes:
        if self._socket is None:
            raise TransportError(ErrorCode.INTERNAL, "DVRIP client is not connected.")
        chunks: list[bytes] = []
        outstanding = count
        while outstanding > 0:
            try:
                chunk = self._socket.recv(outstanding)
            except socket.timeout as exc:
                raise TransportError(ErrorCode.TIMEOUT, "Timed out awaiting a DVRIP frame.", str(exc))
            except OSError as exc:
                raise TransportError(ErrorCode.UNREACHABLE, "DVRIP read failed.", str(exc))
            if not chunk:
                raise TransportError(
                    ErrorCode.PROTOCOL_ERROR,
                    "Recorder closed the DVRIP connection mid-frame.",
                )
            chunks.append(chunk)
            outstanding -= len(chunk)
        return b"".join(chunks)

    def login(self) -> dict:
        self.attempted.append("dvrip:login")
        response = self._send(
            LOGIN_REQUEST,
            {
                "EncryptType": "MD5",
                "LoginType": "DVRIP-Web",
                "PassWord": sofia_hash(self.password),
                "UserName": self.username,
            },
        )
        if response.get("Ret") not in (RET_OK, 515):
            raise TransportError(
                ErrorCode.AUTH_FAILED,
                "Recorder rejected the supplied DVRIP credentials.",
                f"Login returned Ret={response.get('Ret')}.",
            )
        self.succeeded.append("dvrip:login")
        return response

    def get_info(self, name: str) -> dict:
        """Query one named information block (SystemInfo, StorageInfo, ...)."""
        endpoint = f"dvrip:{name}"
        self.attempted.append(endpoint)
        response = self._send(
            GET_INFO_REQUEST, {"Name": name, "SessionID": f"0x{self.session:08X}"}
        )
        if response.get("Ret") == RET_OK:
            self.succeeded.append(endpoint)
        return response

    def get_time(self) -> dict:
        self.attempted.append("dvrip:OPTimeQuery")
        response = self._send(
            TIME_QUERY_REQUEST, {"Name": "OPTimeQuery", "SessionID": f"0x{self.session:08X}"}
        )
        if response.get("Ret") == RET_OK:
            self.succeeded.append("dvrip:OPTimeQuery")
        return response

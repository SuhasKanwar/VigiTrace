"""Shared plumbing for the mock recorders.

The mocks validate RFC 2617 digest authentication for real. A mock that merely
looked at the presence of an ``Authorization`` header would let a broken
credential path through silently, and the whole point of these servers is to
exercise the transport's auth negotiation against something that can actually
say no.

Every server binds port 0 so a test run never collides with a real service or
with a parallel run, and every response carries an explicit ``Content-Length``
because the handlers speak HTTP/1.1 with keep-alive (urllib3 reuses the
connection between the challenge probe and the authenticated request).
"""

import base64
import hashlib
import re
import secrets
import socketserver
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

#: Matches one ``key=value`` or ``key="value"`` pair inside an auth header.
_PARAM_RE = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|([^,\s]+))')


def md5_hex(text: str) -> str:
    """MD5 over UTF-8, the only digest algorithm these recorders offer."""
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def parse_auth_params(header_value: str) -> dict[str, str]:
    """Split a Digest header's comma-separated parameter list.

    Written by hand rather than with ``str.split(",")`` because quoted values
    (``qop="auth"``) and unquoted ones (``nc=00000001``) appear side by side.
    """
    return {
        match.group(1): match.group(2) if match.group(2) is not None else match.group(3)
        for match in _PARAM_RE.finditer(header_value)
    }


class RecordedRequest:
    """One request the mock received, kept so tests can assert on the wire."""

    def __init__(self, verb: str, path: str, query: dict[str, str], body: bytes):
        self.verb = verb
        self.path = path
        self.query = query
        self.body = body

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def __repr__(self) -> str:
        return f"RecordedRequest({self.verb} {self.path} {self.query})"


class MockRecorderServer(ThreadingHTTPServer):
    """A fake recorder listening on an ephemeral loopback port."""

    daemon_threads = True
    allow_reuse_address = True

    #: The digest realm this device advertises. Subclasses set the vendor shape.
    realm: str = "0000000000aa"
    #: Some firmware generations only offer Basic. The transport is supposed to
    #: read the challenge and follow it rather than assuming Digest.
    auth_scheme: str = "Digest"

    def __init__(
        self,
        handler_class: type[BaseHTTPRequestHandler],
        username: str = "admin",
        password: str = "Vigi#Trace1",
        port: int = 0,
    ):
        # Port 0 for tests, which want an ephemeral port and no collisions. A
        # fixed port is for running this as a standalone recorder that other
        # processes - the end-to-end suite, a manual probe - can point at.
        super().__init__(("127.0.0.1", port), handler_class)
        self.username = username
        self.password = password
        #: Nonces this server actually issued. A response quoting any other
        #: nonce is rejected, so a replayed or invented challenge fails.
        self.nonces: set[str] = set()
        self.opaque = secrets.token_hex(8)
        self.requests: list[RecordedRequest] = []
        #: When true, the 401 body mimics a recorder counting failed attempts,
        #: which the transport must map to AUTH_LOCKOUT_RISK rather than a
        #: plain auth failure.
        self.lockout_warning = False
        #: Endpoints this firmware generation does not implement. Optional
        #: endpoints genuinely vary by model, and the adapter is supposed to
        #: warn rather than fail when one is absent.
        self.disabled_paths: set[str] = set()
        #: Seconds to stall before answering. A recorder under load is the
        #: normal cause of a probe timeout, so it is worth being able to
        #: reproduce one on demand.
        self.response_delay = 0.0
        self._thread: threading.Thread | None = None

    @property
    def host(self) -> str:
        return self.server_address[0]

    @property
    def port(self) -> int:
        return self.server_address[1]

    def server_bind(self) -> None:
        """Bind without the reverse-DNS lookup http.server does by default.

        HTTPServer.server_bind() calls socket.getfqdn(), which blocks for tens
        of seconds on a machine whose resolver has no answer for 127.0.0.1.
        """
        socketserver.TCPServer.server_bind(self)
        self.server_name = "localhost"
        self.server_port = self.server_address[1]

    def handle_error(self, request: object, client_address: object) -> None:
        """A client that hangs up mid-response is expected, not a fault.

        requests aborts the connection whenever it abandons a streamed body,
        and the default handler would dump a traceback into the test output.
        """
        if isinstance(sys.exception(), (ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)

    def start(self) -> "MockRecorderServer":
        # A short poll interval keeps shutdown() near-instant; the default
        # half-second would dominate the runtime of a fast suite.
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

    def record(self, verb: str, path: str, query: dict[str, str], body: bytes) -> None:
        self.requests.append(RecordedRequest(verb, path, query, body))

    def calls_to(self, path: str) -> list[RecordedRequest]:
        return [r for r in self.requests if r.path == path]

    def actions(self, path: str) -> list[str]:
        """The ``action`` query values seen on one CGI path, in order."""
        return [r.query.get("action", "") for r in self.calls_to(path)]

    def issue_nonce(self) -> str:
        nonce = secrets.token_hex(16)
        self.nonces.add(nonce)
        return nonce

    def expected_response(self, params: dict[str, str], verb: str) -> str:
        """Compute the digest response this server expects for a challenge.

        Kept on the server (rather than inline in the handler) so a test can
        call it directly and prove the arithmetic is genuine RFC 2617.
        """
        ha1 = md5_hex(f"{self.username}:{self.realm}:{self.password}")
        ha2 = md5_hex(f"{verb}:{params.get('uri', '')}")
        qop = params.get("qop")
        if qop:
            return md5_hex(
                f"{ha1}:{params.get('nonce', '')}:{params.get('nc', '')}:"
                f"{params.get('cnonce', '')}:{qop}:{ha2}"
            )
        return md5_hex(f"{ha1}:{params.get('nonce', '')}:{ha2}")


class RecorderHandler(BaseHTTPRequestHandler):
    """Base handler: reads the body, checks digest, then routes."""

    protocol_version = "HTTP/1.1"
    server_version = "VigiTraceMock"
    sys_version = ""

    #: The blank device turns this off; it has no auth surface at all.
    requires_auth = True

    server: MockRecorderServer  # narrows the base class's annotation

    def log_message(self, format: str, *args: Any) -> None:
        """Silence stderr; a passing test should print nothing."""

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def _dispatch(self, verb: str) -> None:
        if self.server.response_delay:
            time.sleep(self.server.response_delay)
        # The body must be drained even on a 401: requests reuses the
        # connection for the authenticated retry, and an unread body would be
        # parsed as the head of the next request.
        body = self._read_body()
        parsed = urlparse(self.path)
        query = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        self.server.record(verb, parsed.path, query, body)

        if self.requires_auth and not self._authorized(verb):
            self._send_challenge()
            return

        if parsed.path in self.server.disabled_paths:
            self.not_found()
            return

        self.route(verb, parsed.path, query, body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _authorized(self, verb: str) -> bool:
        header = self.headers.get("Authorization")
        if self.server.auth_scheme == "Basic":
            return self._basic_authorized(header)
        if not header or not header.lower().startswith("digest "):
            return False
        params = parse_auth_params(header[len("digest ") :])
        if params.get("username") != self.server.username:
            return False
        if params.get("realm") != self.server.realm:
            return False
        if params.get("nonce") not in self.server.nonces:
            return False
        # The digest URI is covered by HA2, so a response computed for a
        # different path must not be accepted for this one.
        if params.get("uri") != self.path:
            return False
        expected = self.server.expected_response(params, verb)
        return secrets.compare_digest(expected, params.get("response", ""))

    def _basic_authorized(self, header: str | None) -> bool:
        if not header or not header.lower().startswith("basic "):
            return False
        try:
            decoded = base64.b64decode(header[len("basic ") :]).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return False
        username, _, password = decoded.partition(":")
        return secrets.compare_digest(
            f"{username}:{password}", f"{self.server.username}:{self.server.password}"
        )

    def _send_challenge(self) -> None:
        nonce = self.server.issue_nonce()
        body = (
            b"<?xml version='1.0' encoding='UTF-8'?>\n"
            b"<ResponseStatus><statusCode>4</statusCode>"
            b"<statusString>Invalid Operation</statusString></ResponseStatus>"
        )
        if self.server.lockout_warning:
            body = (
                b"<?xml version='1.0' encoding='UTF-8'?>\n"
                b"<ResponseStatus><statusCode>4</statusCode>"
                b"<statusString>Invalid User or Password, 3 attempts remaining "
                b"before the account is locked</statusString></ResponseStatus>"
            )
        self.send_response(401)
        if self.server.auth_scheme == "Basic":
            self.send_header("WWW-Authenticate", f'Basic realm="{self.server.realm}"')
        else:
            self.send_header(
                "WWW-Authenticate",
                f'Digest realm="{self.server.realm}", qop="auth", '
                f'nonce="{nonce}", opaque="{self.server.opaque}"',
            )
        self.send_header("Content-Type", "application/xml")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def respond(
        self,
        status: int,
        payload: bytes | str,
        content_type: str = "application/xml",
    ) -> None:
        data = payload.encode("utf-8") if isinstance(payload, str) else payload
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def not_found(self) -> None:
        self.respond(404, "<ResponseStatus><statusCode>6</statusCode></ResponseStatus>")

    def route(self, verb: str, path: str, query: dict[str, str], body: bytes) -> None:
        raise NotImplementedError


class BlankHandler(RecorderHandler):
    """A device that speaks neither ISAPI nor Dahua CGI.

    It answers, so the host is plainly reachable; nothing it returns matches
    any adapter's fingerprint, which is what makes it the UNKNOWN-vendor case.
    """

    requires_auth = False

    def route(self, verb: str, path: str, query: dict[str, str], body: bytes) -> None:
        if path == "/":
            self.respond(
                200,
                "<html><head><title>Web Viewer</title></head><body>Login</body></html>",
                "text/html",
            )
            return
        self.respond(404, "not found", "text/plain")


class BlankServer(MockRecorderServer):
    """An HTTP surface with no vendor identity and no auth challenge."""

    realm = ""

    def __init__(self) -> None:
        super().__init__(BlankHandler)

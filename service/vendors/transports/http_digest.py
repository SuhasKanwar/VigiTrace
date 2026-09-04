"""HTTP transport shared by the Hikvision and Dahua adapter families.

Two behaviours here are deliberate rather than incidental:

1. **Auth scheme is negotiated, not assumed.** The first request is sent
   unauthenticated so the recorder's ``WWW-Authenticate`` challenge can be
   read. Both vendor families answer 401 with a realm that identifies the
   device before any credential is offered - Hikvision's realm is the bare MAC
   (``realm="4419b66d2485"``) and Dahua's is ``DH_`` plus the MAC
   (``realm="DH_00408CA5EA04"``). That challenge is therefore both the correct
   way to pick Digest vs Basic and a free pre-authentication fingerprint.

2. **Every response is retained verbatim.** Normalization must not destroy
   provenance, so each call records the exact body and its SHA-256 alongside
   the parsed view.
"""

import hashlib
import re
from datetime import datetime, timezone

import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from models.common import ErrorCode, ProbeMethod
from models.device import RawArtifact

_REALM_RE = re.compile(r'realm\s*=\s*"([^"]*)"', re.IGNORECASE)
_SCHEME_RE = re.compile(r"^\s*(Digest|Basic)\b", re.IGNORECASE)


def endpoint_label(path: str, params: dict | None = None) -> str:
    """Canonical identity of one request.

    The query string is part of that identity: without it every Dahua CGI
    action collapses onto one key, and the evidence digest sorts distinct
    payloads under an identical label. Params are sorted so the same call always
    produces the same label.
    """
    if not params:
        return path
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if v is not None)
    return f"{path}?{query}" if query else path


class TransportError(Exception):
    """A wire-level failure, carrying a stable code for the API envelope."""

    def __init__(self, code: ErrorCode, message: str, detail: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


class AuthChallenge:
    """What the recorder revealed before we authenticated."""

    def __init__(self, scheme: str | None, realm: str | None, raw_header: str | None):
        self.scheme = scheme
        self.realm = realm
        self.raw_header = raw_header

    @property
    def realm_mac(self) -> str | None:
        """The MAC embedded in the realm, if the realm carries one."""
        if not self.realm:
            return None
        candidate = self.realm[3:] if self.realm.upper().startswith("DH_") else self.realm
        return candidate if re.fullmatch(r"[0-9A-Fa-f]{12}", candidate) else None


class HttpDeviceClient:
    """A credentialed HTTP session against one recorder."""

    def __init__(
        self,
        host: str,
        port: int = 80,
        username: str | None = None,
        password: str | None = None,
        use_https: bool = False,
        timeout: float = 8.0,
        verify_tls: bool = False,
        sdk_port: int | None = None,
    ):
        self.host = host
        self.port = port
        #: Vendor private-protocol port, when the operator has moved it off the
        #: family default. Families that do not speak HTTP read it from here.
        self.sdk_port = sdk_port
        self.username = username
        self.password = password
        self.use_https = use_https
        self.timeout = timeout
        self.verify_tls = verify_tls
        self.base_url = f"{'https' if use_https else 'http'}://{host}:{port}"
        self.artifacts: list[RawArtifact] = []
        self.attempted: list[str] = []
        self.succeeded: list[str] = []
        self._challenge: AuthChallenge | None = None
        self._session = requests.Session()

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "HttpDeviceClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def challenge(self, path: str = "/") -> AuthChallenge:
        """Read the auth challenge without offering credentials.

        Cached: the challenge is a property of the device, not of the request.
        """
        if self._challenge is not None:
            return self._challenge
        try:
            response = self._session.get(
                f"{self.base_url}{path}",
                timeout=self.timeout,
                verify=self.verify_tls,
                allow_redirects=False,
            )
        except requests.exceptions.Timeout as exc:
            raise TransportError(ErrorCode.TIMEOUT, f"Timed out contacting {self.host}.", str(exc))
        except requests.exceptions.RequestException as exc:
            raise TransportError(ErrorCode.UNREACHABLE, f"Could not reach {self.host}.", str(exc))

        header = response.headers.get("WWW-Authenticate")
        scheme = None
        realm = None
        if header:
            scheme_match = _SCHEME_RE.match(header)
            scheme = scheme_match.group(1).title() if scheme_match else None
            realm_match = _REALM_RE.search(header)
            realm = realm_match.group(1) if realm_match else None
        self._challenge = AuthChallenge(scheme, realm, header)
        return self._challenge

    def _auth(self):
        if not self.username:
            return None
        password = self.password or ""
        challenge = self._challenge
        if challenge is not None and challenge.scheme == "Basic":
            return HTTPBasicAuth(self.username, password)
        return HTTPDigestAuth(self.username, password)

    def get(self, path: str, method: ProbeMethod, **params: object) -> RawArtifact:
        return self.request("GET", path, method, params=params or None)

    def request(
        self,
        verb: str,
        path: str,
        method: ProbeMethod,
        params: dict | None = None,
        data: str | None = None,
        headers: dict | None = None,
    ) -> RawArtifact:
        """Issue one request and record it as a retained artifact.

        Raises TransportError on transport failure or auth rejection; returns
        the artifact for any HTTP status the device actually answered with.
        """
        label = endpoint_label(path, params)
        self.attempted.append(label)
        try:
            self.challenge()
        except TransportError:
            raise

        url = f"{self.base_url}{path}"
        try:
            response = self._session.request(
                verb,
                url,
                params=params,
                data=data.encode("utf-8") if isinstance(data, str) else data,
                headers=headers,
                auth=self._auth(),
                timeout=self.timeout,
                verify=self.verify_tls,
            )
        except requests.exceptions.Timeout as exc:
            raise TransportError(ErrorCode.TIMEOUT, f"Timed out on {path}.", str(exc))
        except requests.exceptions.RequestException as exc:
            raise TransportError(ErrorCode.UNREACHABLE, f"Request to {path} failed.", str(exc))

        body = response.text or ""
        artifact = RawArtifact(
            endpoint=label,
            method=method,
            status_code=response.status_code,
            content_type=response.headers.get("Content-Type"),
            body=body,
            sha256=hashlib.sha256(body.encode("utf-8", "replace")).hexdigest(),
            retrieved_at=datetime.now(timezone.utc),
        )
        self.artifacts.append(artifact)

        if response.status_code in (401, 403):
            # Hikvision reports remaining attempts before lockout. Surface that
            # rather than letting a caller retry a device into a lockout.
            lockout = "lock" in body.lower() or "attempt" in body.lower()
            raise TransportError(
                ErrorCode.AUTH_LOCKOUT_RISK if lockout else ErrorCode.AUTH_FAILED,
                "Recorder rejected the supplied credentials.",
                f"HTTP {response.status_code} on {label}. Retrying may trigger device lockout."
                if lockout
                else f"HTTP {response.status_code} on {label}.",
            )

        if response.ok:
            self.succeeded.append(label)
        return artifact

    def try_get(
        self,
        path: str,
        method: ProbeMethod,
        tolerate_auth_failure: bool = False,
        **params: object,
    ) -> RawArtifact | None:
        """A GET whose failure is tolerable.

        Optional endpoints vary by model and firmware; a missing one is a gap in
        the record, not a failed probe.

        Auth failures propagate by default, so a wrong password during
        identification surfaces instead of looking like a missing endpoint.
        Fingerprinting passes ``tolerate_auth_failure`` because it runs before
        any credential is offered: a 401 there is a positive signal that the
        endpoint exists, not an error.
        """
        try:
            artifact = self.get(path, method, **params)
        except TransportError as exc:
            if exc.code in (ErrorCode.AUTH_FAILED, ErrorCode.AUTH_LOCKOUT_RISK):
                if not tolerate_auth_failure:
                    raise
                return None
            return None
        return artifact if artifact.status_code and artifact.status_code < 400 else None

    def stream_to_file(
        self,
        verb: str,
        path: str,
        destination: str,
        data: str | None = None,
        headers: dict | None = None,
        params: dict | None = None,
    ) -> tuple[int, str, str]:
        """Stream a response body to disk, hashing as it goes.

        Returns ``(bytes_written, md5, sha256)``. Hashes are computed on the
        stream rather than by re-reading the file, so the digest provably covers
        exactly the bytes that were received.
        """
        import hashlib as _hashlib

        label = endpoint_label(path, params)
        self.attempted.append(label)
        self.challenge()
        md5 = _hashlib.md5()
        sha256 = _hashlib.sha256()
        written = 0
        try:
            with self._session.request(
                verb,
                f"{self.base_url}{path}",
                params=params,
                data=data.encode("utf-8") if isinstance(data, str) else data,
                headers=headers,
                auth=self._auth(),
                timeout=self.timeout,
                verify=self.verify_tls,
                stream=True,
            ) as response:
                if response.status_code in (401, 403):
                    raise TransportError(
                        ErrorCode.AUTH_FAILED,
                        "Recorder rejected credentials during acquisition.",
                        f"HTTP {response.status_code} on {path}.",
                    )
                if not response.ok:
                    raise TransportError(
                        ErrorCode.PROTOCOL_ERROR,
                        "Recorder refused the acquisition request.",
                        f"HTTP {response.status_code} on {path}.",
                    )
                with open(destination, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        md5.update(chunk)
                        sha256.update(chunk)
                        written += len(chunk)
        except requests.exceptions.Timeout as exc:
            raise TransportError(ErrorCode.TIMEOUT, f"Acquisition timed out on {path}.", str(exc))
        except requests.exceptions.RequestException as exc:
            raise TransportError(ErrorCode.UNREACHABLE, f"Acquisition failed on {path}.", str(exc))

        self.succeeded.append(label)
        return written, md5.hexdigest(), sha256.hexdigest()

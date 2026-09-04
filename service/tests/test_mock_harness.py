"""The harness itself has to be trustworthy before anything is asserted on it.

If the mocks accepted any Authorization header, a broken credential path in the
transport would pass silently, so these tests prove the digest arithmetic is
real RFC 2617 and that the realms carry the vendor-discriminating shapes.
"""

import hashlib
import re

import pytest
import requests
from requests.auth import HTTPBasicAuth, HTTPDigestAuth

from tests.conftest import PASSWORD, USERNAME
from tests.mock_dvr import parse_auth_params
from tests.mock_dvr.dahua import MAGICBOX
from tests.mock_dvr.hikvision import DEVICE_INFO


def _url(server, path: str) -> str:
    return f"http://{server.host}:{server.port}{path}"


def test_unauthenticated_request_returns_a_digest_challenge(hikvision_server):
    response = requests.get(_url(hikvision_server, DEVICE_INFO), timeout=5)

    assert response.status_code == 401
    header = response.headers["WWW-Authenticate"]
    params = parse_auth_params(header)
    assert header.startswith("Digest ")
    assert params["qop"] == "auth"
    assert len(params["nonce"]) == 32


def test_hikvision_realm_is_a_bare_mac(hikvision_server):
    """The bare 12-hex realm is the Hikvision family discriminator."""
    response = requests.get(_url(hikvision_server, "/"), timeout=5)

    realm = parse_auth_params(response.headers["WWW-Authenticate"])["realm"]
    assert re.fullmatch(r"[0-9a-f]{12}", realm)
    assert not realm.upper().startswith("DH_")


def test_dahua_realm_carries_the_dh_prefix(dahua_server):
    """Dahua prefixes the MAC with DH_, which separates it from Hikvision."""
    response = requests.get(_url(dahua_server, "/"), timeout=5)

    realm = parse_auth_params(response.headers["WWW-Authenticate"])["realm"]
    assert re.fullmatch(r"DH_[0-9A-F]{12}", realm)


def test_correct_digest_credentials_are_accepted(hikvision_server):
    response = requests.get(
        _url(hikvision_server, DEVICE_INFO),
        auth=HTTPDigestAuth(USERNAME, PASSWORD),
        timeout=5,
    )

    assert response.status_code == 200
    assert "<DeviceInfo" in response.text


def test_wrong_password_is_rejected(hikvision_server):
    response = requests.get(
        _url(hikvision_server, DEVICE_INFO),
        auth=HTTPDigestAuth(USERNAME, "not-the-password"),
        timeout=5,
    )

    assert response.status_code == 401


def test_basic_auth_is_rejected_by_a_digest_only_device(dahua_server):
    """Offering the password in the clear must not shortcut the challenge."""
    response = requests.get(
        _url(dahua_server, MAGICBOX),
        params={"action": "getSystemInfo"},
        auth=HTTPBasicAuth(USERNAME, PASSWORD),
        timeout=5,
    )

    assert response.status_code == 401


def test_digest_response_is_verified_against_rfc_2617_arithmetic(hikvision_server):
    """Compute the response by hand; only the exact digest may be accepted."""
    challenge = requests.get(_url(hikvision_server, DEVICE_INFO), timeout=5)
    params = parse_auth_params(challenge.headers["WWW-Authenticate"])
    nonce = params["nonce"]
    realm = params["realm"]
    cnonce = "0a4f19c7de2b8135"
    nc = "00000001"

    def md5(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    ha1 = md5(f"{USERNAME}:{realm}:{PASSWORD}")
    ha2 = md5(f"GET:{DEVICE_INFO}")
    digest = md5(f"{ha1}:{nonce}:{nc}:{cnonce}:auth:{ha2}")
    header = (
        f'Digest username="{USERNAME}", realm="{realm}", nonce="{nonce}", '
        f'uri="{DEVICE_INFO}", response="{digest}", qop="auth", nc={nc}, '
        f'cnonce="{cnonce}"'
    )

    accepted = requests.get(
        _url(hikvision_server, DEVICE_INFO), headers={"Authorization": header}, timeout=5
    )
    assert accepted.status_code == 200

    tampered = header.replace(f'response="{digest}"', f'response="{"0" * 32}"')
    rejected = requests.get(
        _url(hikvision_server, DEVICE_INFO), headers={"Authorization": tampered}, timeout=5
    )
    assert rejected.status_code == 401


def test_a_response_computed_for_another_uri_is_rejected(hikvision_server):
    """HA2 covers the URI, so a digest lifted from another request must fail."""
    challenge = requests.get(_url(hikvision_server, DEVICE_INFO), timeout=5)
    params = parse_auth_params(challenge.headers["WWW-Authenticate"])

    def md5(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    ha1 = md5(f"{USERNAME}:{params['realm']}:{PASSWORD}")
    ha2 = md5(f"GET:/ISAPI/System/time")
    digest = md5(f"{ha1}:{params['nonce']}:00000001:abc123:auth:{ha2}")
    header = (
        f'Digest username="{USERNAME}", realm="{params["realm"]}", '
        f'nonce="{params["nonce"]}", uri="{DEVICE_INFO}", response="{digest}", '
        f'qop="auth", nc=00000001, cnonce="abc123"'
    )

    response = requests.get(
        _url(hikvision_server, DEVICE_INFO), headers={"Authorization": header}, timeout=5
    )
    assert response.status_code == 401


def test_an_invented_nonce_is_rejected(hikvision_server):
    """Only nonces this server issued are honoured, so replay needs a challenge."""

    def md5(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    nonce = "f" * 32
    ha1 = md5(f"{USERNAME}:{hikvision_server.realm}:{PASSWORD}")
    ha2 = md5(f"GET:{DEVICE_INFO}")
    digest = md5(f"{ha1}:{nonce}:00000001:abc123:auth:{ha2}")
    header = (
        f'Digest username="{USERNAME}", realm="{hikvision_server.realm}", '
        f'nonce="{nonce}", uri="{DEVICE_INFO}", response="{digest}", '
        f'qop="auth", nc=00000001, cnonce="abc123"'
    )

    response = requests.get(
        _url(hikvision_server, DEVICE_INFO), headers={"Authorization": header}, timeout=5
    )
    assert response.status_code == 401


def test_mock_sofia_hash_matches_the_service_implementation():
    """The mock re-implements the digest; both must agree on known inputs."""
    from tests.mock_dvr.dvrip import sofia_hash as mock_hash
    from vendors.transports.dvrip import sofia_hash as service_hash

    for password in ("", "admin", "Vigi#Trace1", "1234567890"):
        assert mock_hash(password) == service_hash(password)

    # The empty-password digest is the value every XiongMai capture shows.
    assert mock_hash("") == "tlJwpbo6"


@pytest.mark.parametrize("path", ["/", "/ISAPI/System/deviceInfo"])
def test_blank_device_offers_no_auth_challenge(blank_server, path):
    """The unknown-vendor case is reachable but fingerprints as nothing."""
    response = requests.get(_url(blank_server, path), timeout=5)

    assert "WWW-Authenticate" not in response.headers

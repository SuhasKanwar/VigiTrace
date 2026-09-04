"""Fixtures for the VigiTrace service suite.

Every fixture is function-scoped: the mocks carry mutable behaviour flags
(fail the next find, return a single match, warn about lockout) and a shared
server would leak one test's tampering into the next. Starting a threaded
loopback server costs about a millisecond, so isolation is cheap.
"""

import socket
from collections.abc import Iterator

import pytest

from models.probe import DeviceCredentials, DeviceTarget
from tests.mock_dvr import BlankServer, DahuaServer, DvripServer, HikvisionServer
from vendors.transports.http_digest import HttpDeviceClient

USERNAME = "admin"
PASSWORD = "Vigi#Trace1"


@pytest.fixture
def hikvision_server() -> Iterator[HikvisionServer]:
    """A Hikvision DVR reachable over ISAPI."""
    server = HikvisionServer().start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def hikvision_nvr_server() -> Iterator[HikvisionServer]:
    """The same recorder reporting deviceType NVR instead of DVR."""
    server = HikvisionServer(device_type="NVR").start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def dahua_server() -> Iterator[DahuaServer]:
    """An unbranded Dahua recorder."""
    server = DahuaServer().start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def cpplus_server() -> Iterator[DahuaServer]:
    """The same Dahua CGI surface with CP Plus branding and firmware."""
    server = DahuaServer(cpplus=True).start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def blank_server() -> Iterator[BlankServer]:
    """A reachable HTTP host that is not a supported recorder."""
    server = BlankServer().start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def dvrip_server() -> Iterator[DvripServer]:
    """A XiongMai-lineage recorder speaking DVRIP."""
    server = DvripServer(username=USERNAME, password=PASSWORD).start()
    try:
        yield server
    finally:
        server.stop()


def make_client(
    server,
    username: str | None = USERNAME,
    password: str | None = PASSWORD,
    timeout: float = 5.0,
    sdk_port: int | None = None,
) -> HttpDeviceClient:
    """Build a transport client aimed at one mock recorder.

    ``sdk_port`` carries the vendor private-protocol port for families that do
    not speak HTTP at all, which is how the DVRIP mock is reached on its
    ephemeral port.
    """
    return HttpDeviceClient(
        host=server.host,
        port=server.port,
        username=username,
        password=password,
        timeout=timeout,
        sdk_port=sdk_port,
    )


def make_target(
    server,
    username: str | None = USERNAME,
    password: str | None = PASSWORD,
    **overrides,
) -> DeviceTarget:
    """Build the request envelope the service layer takes."""
    credentials = (
        DeviceCredentials(username=username, password=password or "")
        if username is not None
        else None
    )
    return DeviceTarget(
        host=server.host,
        http_port=server.port,
        credentials=credentials,
        timeout_seconds=5.0,
        **overrides,
    )


@pytest.fixture
def client_factory():
    """Hand out transport clients and close them all at teardown."""
    created: list[HttpDeviceClient] = []

    def factory(server, **kwargs) -> HttpDeviceClient:
        client = make_client(server, **kwargs)
        created.append(client)
        return client

    try:
        yield factory
    finally:
        for client in created:
            client.close()


@pytest.fixture
def hik_client(hikvision_server, client_factory) -> HttpDeviceClient:
    return client_factory(hikvision_server)


@pytest.fixture
def dahua_client(dahua_server, client_factory) -> HttpDeviceClient:
    return client_factory(dahua_server)


@pytest.fixture
def cpplus_client(cpplus_server, client_factory) -> HttpDeviceClient:
    return client_factory(cpplus_server)


@pytest.fixture
def closed_port() -> int:
    """A loopback port with nothing listening on it.

    Bound and released so the number is known to have been free a moment ago,
    which is the closest a test can get to a deterministic refused connection.
    """
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


@pytest.fixture
def evidence_dir(tmp_path, monkeypatch):
    """Redirect acquired evidence into the test's own temp directory."""
    destination = tmp_path / "evidence"
    monkeypatch.setattr("services.probe.EVIDENCE_DIR", str(destination))
    return destination


@pytest.fixture
def api_client():
    """A FastAPI test client. Imported lazily so app import cost is paid once."""
    from fastapi.testclient import TestClient

    from app import app

    with TestClient(app) as client:
        yield client

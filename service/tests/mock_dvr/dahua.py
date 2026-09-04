"""A mock Dahua (and CP Plus) recorder speaking the HTTP CGI API.

Responses are the flat ``key=value`` documents the "API of HTTP Protocol
Specification" describes, including the bracketed-index encoding Dahua uses to
express arrays (``items[0].Channel=1``). The digest realm is ``DH_`` plus the
MAC, which is what separates this family from Hikvision before authentication.

The CP Plus variant is the same firmware with OEM branding, so it is the same
handler with ``getVendor``/``getSoftwareVersion`` swapped - which is exactly the
only thing the CP Plus adapter can key off.
"""

from datetime import datetime, timedelta, timezone

from tests.mock_dvr.base import MockRecorderServer, RecorderHandler

MAGICBOX = "/cgi-bin/magicBox.cgi"
GLOBAL_CGI = "/cgi-bin/global.cgi"
CONFIG_MANAGER = "/cgi-bin/configManager.cgi"
STORAGE_DEVICE = "/cgi-bin/storageDevice.cgi"
DEV_VIDEO_INPUT = "/cgi-bin/devVideoInput.cgi"
MEDIA_FILE_FIND = "/cgi-bin/mediaFileFind.cgi"
LOADFILE = "/cgi-bin/RPC_Loadfile"

#: DH_ + 12 hex digits. The prefix is the Dahua-family discriminator.
REALM = "DH_00408CA5EA04"
REALM_MAC = "00408CA5EA04"

DEVICE_TYPE = "NVR4216"
SERIAL_NUMBER = "YZC4CS1PAJE7A5D"
HARDWARE_VERSION = "1.00"
MACHINE_NAME = "NVR-Basement"
SOFTWARE_VERSION = "2.212.0000.0.R,build:2013-11-14"

#: Dahua-built-for-CP-Plus firmware carries the 'AT' vendor token; together
#: with the branded getVendor response it is all the CP Plus adapter has.
CPPLUS_SOFTWARE_VERSION = "V4.001.00AT009.0.R,build:2019-06-11"
CPPLUS_DEVICE_TYPE = "CP-UNR-4K4162-V2"
CPPLUS_MACHINE_NAME = "CP-PLUS-NVR"

#: storageDevice.cgi reports these figures in MEGABYTES.
STORAGE_TOTAL_MB = 1907729
STORAGE_USED_MB = 1805329

DEVICE_TIME = "2026-09-04 10:00:00"

FINDER_HANDLE = "08137"

#: Three segments on channel 1 with a deliberate 30-minute hole between the
#: second and the third.
SEGMENTS = (
    ("2026-09-04 08:00:00", "2026-09-04 09:00:00", 104857600, 5),
    ("2026-09-04 09:00:00", "2026-09-04 10:00:00", 103809024, 0),
    ("2026-09-04 10:30:00", "2026-09-04 11:00:00", 52428800, 0),
)
GAP_SECONDS = 1800

DOWNLOAD_PAYLOAD = bytes(range(200, 256)) * 73  # 4088 bytes, deterministic


def _kv(lines: list[str]) -> str:
    """Dahua terminates every key/value line with CRLF."""
    return "".join(f"{line}\r\n" for line in lines)


class DahuaHandler(RecorderHandler):
    """Routes the CGI surface the adapter actually calls."""

    def route(self, verb: str, path: str, query: dict[str, str], body: bytes) -> None:
        server: "DahuaServer" = self.server  # type: ignore[assignment]
        action = query.get("action", "")

        if path == "/":
            self.respond(200, "<html><body>WEB SERVICE</body></html>", "text/html")
            return
        if path == MAGICBOX:
            self._magic_box(server, action)
            return
        if path == GLOBAL_CGI and action == "getCurrentTime":
            self.respond(200, _kv([f"result={server.local_time()}"]), "text/plain")
            return
        if path == CONFIG_MANAGER and action == "getConfig" and query.get("name") == "NTP":
            self.respond(200, server.ntp_config(), "text/plain")
            return
        if path == STORAGE_DEVICE and action == "getDeviceAllInfo":
            self.respond(200, server.storage_info(), "text/plain")
            return
        if path == DEV_VIDEO_INPUT and action == "getCollect":
            self.respond(200, server.channels(), "text/plain")
            return
        if path == MEDIA_FILE_FIND:
            self._media_file_find(server, action, query)
            return
        if path.startswith(f"{LOADFILE}/"):
            self.respond(200, server.download_payload, "application/octet-stream")
            return
        self.respond(400, _kv(["Error"]), "text/plain")

    def _magic_box(self, server: "DahuaServer", action: str) -> None:
        system_info = [
            f"deviceType={server.device_type}",
            f"hardwareVersion={HARDWARE_VERSION}",
            "processor=S2L",
        ]
        if server.serial_in_system_info:
            system_info.append(f"serialNumber={SERIAL_NUMBER}")
        payloads = {
            "getSystemInfo": _kv(system_info),
            "getSerialNo": _kv([f"sn={SERIAL_NUMBER}"]),
            "getSoftwareVersion": _kv([f"version={server.software_version}"]),
            "getMachineName": _kv([f"name={server.machine_name}"]),
            "getVendor": _kv([f"vendor={server.vendor_string}"]),
            "getDeviceType": _kv([f"type={server.device_type}"]),
        }
        payload = payloads.get(action)
        if payload is None:
            self.respond(400, _kv(["Error"]), "text/plain")
            return
        self.respond(200, payload, "text/plain")

    def _media_file_find(
        self, server: "DahuaServer", action: str, query: dict[str, str]
    ) -> None:
        if action == "factory.create":
            self.respond(200, _kv([f"result={FINDER_HANDLE}"]), "text/plain")
            return
        if action == "findFile":
            if server.fail_find_file:
                self.respond(500, _kv(["Error"]), "text/plain")
                return
            self.respond(200, "OK\r\n", "text/plain")
            return
        if action == "findNextFile":
            if server.fail_find_next or server.page_is_refused():
                # A recorder that errors mid-search still holds the finder
                # object, so the adapter must release it on this path too.
                self.respond(500, _kv(["Error"]), "text/plain")
                return
            self.respond(200, server.find_next(int(query.get("count") or 100)), "text/plain")
            return
        if action in ("close", "destroy"):
            self.respond(200, "OK\r\n", "text/plain")
            return
        self.respond(400, _kv(["Error"]), "text/plain")


class DahuaServer(MockRecorderServer):
    """A Dahua-family recorder; ``cpplus=True`` gives it CP Plus branding."""

    realm = REALM

    def __init__(self, cpplus: bool = False) -> None:
        super().__init__(DahuaHandler)
        self.cpplus = cpplus
        self.device_type = CPPLUS_DEVICE_TYPE if cpplus else DEVICE_TYPE
        self.software_version = CPPLUS_SOFTWARE_VERSION if cpplus else SOFTWARE_VERSION
        self.machine_name = CPPLUS_MACHINE_NAME if cpplus else MACHINE_NAME
        #: Dahua answers 'General' for its own units and the OEM name for a
        #: rebadge; this single string is the strongest CP Plus signal.
        self.vendor_string = "CP PLUS" if cpplus else "General"
        self.device_time = DEVICE_TIME
        #: When set, the recorder reports the probing host's clock plus this
        #: offset, which makes a drift assertion exact instead of approximate.
        self.clock_offset_seconds: float | None = None
        self.fail_find_next = False
        #: Refuse the search outright, before any page is read.
        self.fail_find_file = False
        #: Refuse from this findNextFile call onwards (1-based), so a search can
        #: be interrupted after it has already returned real segments.
        self.fail_find_next_after: int | None = None
        self.single_item = False
        #: Fill every page to the requested count, which is what makes the
        #: adapter ask for another one.
        self.full_pages = False
        #: Report Flags as a bare string rather than the indexed array form.
        self.scalar_flags = False
        self._pages_served = 0
        #: Older firmware omits serialNumber from getSystemInfo and only
        #: answers it under getSerialNo, which is why the adapter asks twice.
        self.serial_in_system_info = True
        self.download_payload = DOWNLOAD_PAYLOAD

    def local_time(self) -> str:
        if self.clock_offset_seconds is None:
            return self.device_time
        moment = datetime.now(timezone.utc) + timedelta(seconds=self.clock_offset_seconds)
        return moment.strftime("%Y-%m-%d %H:%M:%S")

    def ntp_config(self) -> str:
        return _kv(
            [
                "table.NTP.Address=clock.isc.org",
                "table.NTP.Enable=true",
                "table.NTP.Port=123",
                "table.NTP.TimeZone=5",
                "table.NTP.UpdatePeriod=10",
            ]
        )

    def storage_info(self) -> str:
        return _kv(
            [
                "list[0].Name=/dev/sda0",
                "list[0].State=Running",
                "list[0].Detail[0].Path=/mnt/dvr/sda0",
                f"list[0].Detail[0].TotalBytes={STORAGE_TOTAL_MB}",
                f"list[0].Detail[0].UsedBytes={STORAGE_USED_MB}",
                "list[0].Detail[0].Type=Read/Write",
                "list[0].Detail[0].IsError=false",
            ]
        )

    def channels(self) -> str:
        names = ("Front Gate", "Reception", "Corridor", "Store Room")
        lines: list[str] = []
        for index, name in enumerate(names):
            lines.append(f"channels[{index}].Channel={index + 1}")
            lines.append(f"channels[{index}].Name={name}")
            lines.append(f"channels[{index}].Enable=true")
        return _kv(lines)

    def page_is_refused(self) -> bool:
        """Whether this findNextFile call is the one that fails."""
        if self.fail_find_next_after is None:
            return False
        return self._pages_served >= self.fail_find_next_after

    def _page(self, count: int) -> tuple[tuple[str, str, int, int], ...]:
        """One page of consecutive minute-long segments, for pagination tests."""
        base = datetime(2026, 9, 4, 0, 0, tzinfo=timezone.utc) + timedelta(
            minutes=self._pages_served * count
        )
        page = []
        for index in range(count):
            start = base + timedelta(minutes=index)
            page.append(
                (
                    start.strftime("%Y-%m-%d %H:%M:%S"),
                    (start + timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
                    1048576,
                    0,
                )
            )
        return tuple(page)

    def find_next(self, count: int = 100) -> str:
        if self.full_pages:
            segments = self._page(count)
        elif self.single_item:
            segments = SEGMENTS[:1]
        else:
            segments = SEGMENTS
        self._pages_served += 1
        lines = [f"found={len(segments)}"]
        for index, (start, end, length, overwrites) in enumerate(segments):
            stamp = start.split(" ")[1].replace(":", ".")
            stop = end.split(" ")[1].replace(":", ".")
            lines.extend(
                [
                    f"items[{index}].Channel=1",
                    f"items[{index}].StartTime={start}",
                    f"items[{index}].EndTime={end}",
                    f"items[{index}].Type=dav",
                    f"items[{index}].FilePath=/mnt/dvr/sda0/2026/9/4/dav/{stamp}-{stop}.dav",
                    f"items[{index}].Length={length}",
                    f"items[{index}].Overwrites={overwrites}",
                    f"items[{index}].Cluster={index + 1}",
                    f"items[{index}].Partition=1",
                    f"items[{index}].Disk=1",
                    f"items[{index}].VideoStream=Main",
                    # Dahua encodes Flags and Events as arrays; a few
                    # firmware builds report a bare scalar instead.
                    (
                        f"items[{index}].Flags=Manual"
                        if self.scalar_flags
                        else f"items[{index}].Flags[0]=Timing"
                    ),
                    f"items[{index}].Events[0]=VideoMotion",
                ]
            )
        return _kv(lines)

    def file_path(self, index: int = 0) -> str:
        start, end, _length, _overwrites = SEGMENTS[index]
        stamp = start.split(" ")[1].replace(":", ".")
        stop = end.split(" ")[1].replace(":", ".")
        return f"/mnt/dvr/sda0/2026/9/4/dav/{stamp}-{stop}.dav"

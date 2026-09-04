"""A mock Hikvision recorder speaking ISAPI over digest-authenticated HTTP.

Payload shapes follow the Intelligent Security API (General Application)
developer guide: namespaced XML documents, capacities in megabytes, and the
``playbackURI`` that carries the exact byte length of a segment in a ``size``
query parameter. The digest realm is the bare 12-hex MAC, which is the
pre-authentication discriminator between this family and Dahua's ``DH_`` realm.
"""

from datetime import datetime, timedelta, timezone

from tests.mock_dvr.base import MockRecorderServer, RecorderHandler

DEVICE_INFO = "/ISAPI/System/deviceInfo"
VIDEO_INPUT_CHANNELS = "/ISAPI/System/Video/inputs/channels"
INPUT_PROXY_CHANNELS = "/ISAPI/ContentMgmt/InputProxy/channels"
STORAGE_HDD = "/ISAPI/ContentMgmt/Storage/hdd"
SYSTEM_TIME = "/ISAPI/System/time"
NTP_SERVERS = "/ISAPI/System/time/ntpServers"
CONTENT_SEARCH = "/ISAPI/ContentMgmt/search"
CONTENT_DOWNLOAD = "/ISAPI/ContentMgmt/download"

NAMESPACE = "http://www.hikvision.com/ver20/XMLSchema"

#: 12 hex digits with no separator: exactly what a Hikvision recorder puts in
#: its digest realm, and the reason the transport can name the vendor before
#: any credential is offered.
REALM_MAC = "4419b66d2485"

SERIAL_NUMBER = "DS-7208HQHI-K10420200714AAWR123456789WCVU"
MODEL = "DS-7208HQHI-K1"
FIRMWARE_VERSION = "V4.30.005"
FIRMWARE_RELEASED = "build 200606"
HARDWARE_VERSION = "0x0"
MAC_ADDRESS = "44:19:b6:6d:24:85"
DEVICE_NAME = "Embedded Net DVR"

#: Reported by /ISAPI/ContentMgmt/Storage/hdd in MEGABYTES.
HDD_CAPACITY_MB = 1907729
HDD_FREE_MB = 102400

#: The recorder's own clock, fixed so drift assertions are reproducible.
DEVICE_TIME = "2026-09-04T10:00:00Z"

#: Three segments with a deliberate 30-minute hole between the second and the
#: third, so RecordingIndex.gaps() has something real to find.
SEGMENTS = (
    ("20260904T080000Z", "20260904T090000Z", 260358144),
    ("20260904T090000Z", "20260904T100000Z", 259817472),
    ("20260904T103000Z", "20260904T110000Z", 129548288),
)
GAP_SECONDS = 1800

#: Deterministic export payload: 4 KiB whose hashes a test can recompute.
DOWNLOAD_PAYLOAD = bytes(range(256)) * 16


def _isapi_timestamp(value: str) -> str:
    """Rewrite a compact ISAPI stamp (``20260904T080000Z``) as extended ISO."""
    return f"{value[0:4]}-{value[4:6]}-{value[6:8]}T{value[9:11]}:{value[11:13]}:{value[13:15]}Z"


class HikvisionHandler(RecorderHandler):
    """Routes the ISAPI endpoints the adapter actually calls."""

    def route(self, verb: str, path: str, query: dict[str, str], body: bytes) -> None:
        server: "HikvisionServer" = self.server  # type: ignore[assignment]

        if verb == "GET" and path == "/":
            self.respond(200, "<html><body>Hikvision</body></html>", "text/html")
            return
        if verb == "GET" and path == DEVICE_INFO:
            self.respond(200, server.device_info_xml())
            return
        if verb == "GET" and path == VIDEO_INPUT_CHANNELS:
            self.respond(200, server.video_inputs_xml())
            return
        if verb == "GET" and path == INPUT_PROXY_CHANNELS:
            self.respond(200, server.input_proxy_xml())
            return
        if verb == "GET" and path == STORAGE_HDD:
            self.respond(200, server.hdd_xml())
            return
        if verb == "GET" and path == SYSTEM_TIME:
            self.respond(200, server.time_xml())
            return
        if verb == "GET" and path == NTP_SERVERS:
            self.respond(200, server.ntp_xml())
            return
        if verb == "POST" and path == CONTENT_SEARCH:
            self.respond(200, server.search_xml())
            return
        if verb == "POST" and path == CONTENT_DOWNLOAD:
            self.respond(200, server.download_payload, "application/octet-stream")
            return
        self.not_found()


class HikvisionServer(MockRecorderServer):
    """A Hikvision DVR/NVR whose behaviour individual tests can steer."""

    realm = REALM_MAC

    def __init__(self, device_type: str = "DVR") -> None:
        super().__init__(HikvisionHandler)
        self.device_type = device_type
        #: When set, the recorder's clock is reported as the probing host's
        #: clock plus this offset, which makes drift assertions exact.
        self.clock_offset_seconds: float | None = None
        self.device_time = DEVICE_TIME
        #: xmltodict collapses a one-element list into a bare dict; this flag
        #: forces that case so as_list() is exercised on recordings too.
        self.single_match = False
        #: Drives the CMSearchResult status the adapter reads as "truncated".
        self.more_results = False
        self.download_payload = DOWNLOAD_PAYLOAD

    def local_time(self) -> str:
        if self.clock_offset_seconds is None:
            return self.device_time
        moment = datetime.now(timezone.utc) + timedelta(seconds=self.clock_offset_seconds)
        return moment.strftime("%Y-%m-%dT%H:%M:%SZ")

    def device_info_xml(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<DeviceInfo version="2.0" xmlns="{NAMESPACE}">\n'
            f"<deviceName>{DEVICE_NAME}</deviceName>\n"
            "<deviceID>48504b4a-0f1f-4b3a-9a2d-9c1a2b3c4d5e</deviceID>\n"
            f"<model>{MODEL}</model>\n"
            f"<serialNumber>{SERIAL_NUMBER}</serialNumber>\n"
            f"<macAddress>{MAC_ADDRESS}</macAddress>\n"
            f"<firmwareVersion>{FIRMWARE_VERSION}</firmwareVersion>\n"
            f"<firmwareReleasedDate>{FIRMWARE_RELEASED}</firmwareReleasedDate>\n"
            f"<hardwareVersion>{HARDWARE_VERSION}</hardwareVersion>\n"
            f"<deviceType>{self.device_type}</deviceType>\n"
            "<telecontrolID>255</telecontrolID>\n"
            "</DeviceInfo>\n"
        )

    def video_inputs_xml(self) -> str:
        names = ("Front Gate", "Reception", "Corridor", "Store Room")
        entries = "".join(
            "<VideoInputChannel>"
            f"<id>{index}</id>"
            f"<inputPort>{index}</inputPort>"
            f"<name>{name}</name>"
            "<videoInputEnabled>true</videoInputEnabled>"
            "<videoFormat>PAL</videoFormat>"
            "<resDesc>1920*1080P</resDesc>"
            "</VideoInputChannel>"
            for index, name in enumerate(names, start=1)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<VideoInputChannelList version="2.0" xmlns="{NAMESPACE}">'
            f"{entries}</VideoInputChannelList>\n"
        )

    def input_proxy_xml(self) -> str:
        entries = "".join(
            "<InputProxyChannel>"
            f"<id>{channel_id}</id>"
            f"<name>IP Camera {channel_id - 32:02d}</name>"
            "<sourceInputPortDescriptor>"
            "<proxyProtocol>ONVIF</proxyProtocol>"
            "</sourceInputPortDescriptor>"
            "</InputProxyChannel>"
            for channel_id in (33, 34)
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<InputProxyChannelList version="2.0" xmlns="{NAMESPACE}">'
            f"{entries}</InputProxyChannelList>\n"
        )

    def hdd_xml(self) -> str:
        """A single-disk list, which is also the xmltodict single-item case."""
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<hddList version="2.0" xmlns="{NAMESPACE}">'
            "<hdd>"
            "<id>1</id>"
            "<hddName>hde1</hddName>"
            "<hddPath></hddPath>"
            "<hddType>SATA</hddType>"
            "<status>ok</status>"
            f"<capacity>{HDD_CAPACITY_MB}</capacity>"
            f"<freeSpace>{HDD_FREE_MB}</freeSpace>"
            "<property>RW</property>"
            "</hdd>"
            "</hddList>\n"
        )

    def time_xml(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<Time version="2.0" xmlns="{NAMESPACE}">'
            "<timeMode>NTP</timeMode>"
            f"<localTime>{self.local_time()}</localTime>"
            "<timeZone>CST-5:30:00</timeZone>"
            "</Time>\n"
        )

    def ntp_xml(self) -> str:
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<NTPServerList version="2.0" xmlns="{NAMESPACE}">'
            "<NTPServer>"
            "<id>1</id>"
            "<addressingFormatType>hostname</addressingFormatType>"
            "<hostName>pool.ntp.org</hostName>"
            "<ipAddress>pool.ntp.org</ipAddress>"
            "<portNo>123</portNo>"
            "<synchronizeInterval>60</synchronizeInterval>"
            "<enabled>true</enabled>"
            "</NTPServer>"
            "</NTPServerList>\n"
        )

    def search_xml(self) -> str:
        segments = SEGMENTS[:1] if self.single_match else SEGMENTS
        items = "".join(
            "<searchMatchItem>"
            f"<sourceID>{{0000000{index}-0000-0000-0000-000000000000}}</sourceID>"
            "<trackID>101</trackID>"
            "<timeSpan>"
            f"<startTime>{_isapi_timestamp(start)}</startTime>"
            f"<endTime>{_isapi_timestamp(end)}</endTime>"
            "</timeSpan>"
            "<mediaSegmentDescriptor>"
            "<contentType>video</contentType>"
            "<codecType>H.264-BP</codecType>"
            f"<playbackURI>rtsp://{self.host}/Streaming/tracks/101/"
            f"?starttime={start}&amp;endtime={end}&amp;name=ch01&amp;size={size}"
            "</playbackURI>"
            "</mediaSegmentDescriptor>"
            "<metadataMatches><metadataDescriptor>recordType.timing.regular"
            "</metadataDescriptor></metadataMatches>"
            "</searchMatchItem>"
            for index, (start, end, size) in enumerate(segments, start=1)
        )
        status = "MORE" if self.more_results else "OK"
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<CMSearchResult version="2.0" xmlns="{NAMESPACE}">'
            "<searchID>{11111111-1111-1111-1111-111111111111}</searchID>"
            "<responseStatus>true</responseStatus>"
            f"<responseStatusStrip>{status}</responseStatusStrip>"
            f"<numOfMatches>{len(segments)}</numOfMatches>"
            f"<matchList>{items}</matchList>"
            "</CMSearchResult>\n"
        )

    def playback_uri(self, index: int = 0) -> str:
        """The playbackURI for one segment, as the search would return it."""
        start, end, size = SEGMENTS[index]
        return (
            f"rtsp://{self.host}/Streaming/tracks/101/"
            f"?starttime={start}&endtime={end}&name=ch01&size={size}"
        )

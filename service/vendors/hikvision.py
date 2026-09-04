"""Hikvision adapter, speaking ISAPI over HTTP with digest authentication.

Endpoint set and field names follow Hikvision's Intelligent Security API
(General Application) developer guide. ISAPI - not HCNetSDK - is the transport
because the HIKVISION Materials License Agreement forbids distributing or
incorporating the SDK binaries into another product, while ISAPI is reachable
over plain HTTP and needs no vendor code.
"""

import re
import uuid
from datetime import datetime, timezone
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlparse

import xmltodict

from models.common import (
    Capability,
    Confidence,
    DeviceKind,
    ErrorCode,
    ProbeMethod,
    Vendor,
    VendorFamily,
)
from models.device import (
    ChannelInfo,
    ClockInfo,
    DeviceIdentity,
    NetworkInfo,
    StandardizedDevice,
    StorageInfo,
)
from models.recording import (
    AcquisitionResult,
    RecordingIndex,
    StandardizedRecording,
    TimeSpan,
)
from vendors.base import (
    AdapterError,
    Capability as _Capability,
    EvidenceRecorder,
    Fingerprint,
    VendorAdapter,
    mb_to_bytes,
    to_bool,
    to_int,
)
from vendors.transports.http_digest import HttpDeviceClient

_MAC_RE = re.compile(r"^[0-9A-Fa-f]{12}$")

DEVICE_INFO = "/ISAPI/System/deviceInfo"
SYSTEM_STATUS = "/ISAPI/System/status"
INPUT_PROXY_CHANNELS = "/ISAPI/ContentMgmt/InputProxy/channels"
VIDEO_INPUT_CHANNELS = "/ISAPI/System/Video/inputs/channels"
STORAGE_HDD = "/ISAPI/ContentMgmt/Storage/hdd"
SYSTEM_TIME = "/ISAPI/System/time"
NTP_SERVERS = "/ISAPI/System/time/ntpServers"
CONTENT_SEARCH = "/ISAPI/ContentMgmt/search"
CONTENT_DOWNLOAD = "/ISAPI/ContentMgmt/download"

_KIND_MAP = {
    "DVR": DeviceKind.DVR,
    "NVR": DeviceKind.NVR,
    "HYBIRDNVR": DeviceKind.HVR,
    "HYBRIDNVR": DeviceKind.HVR,
    "IPCAMERA": DeviceKind.IPC,
    "IPDOME": DeviceKind.IPC,
    "DVS": DeviceKind.DVR,
    "CVR": DeviceKind.NVR,
}


def strip_namespaces(value: Any) -> Any:
    """ISAPI payloads are namespaced; the namespace carries no evidence value."""
    if isinstance(value, dict):
        return {
            key.split(":")[-1]: strip_namespaces(item)
            for key, item in value.items()
            if not key.startswith("@xmlns")
        }
    if isinstance(value, list):
        return [strip_namespaces(item) for item in value]
    return value


def parse_isapi_xml(body: str) -> dict:
    if not body or not body.strip():
        return {}
    try:
        return strip_namespaces(xmltodict.parse(body)) or {}
    except Exception as exc:  # xmltodict raises a variety of parser errors
        raise AdapterError(
            ErrorCode.PROTOCOL_ERROR,
            "Recorder returned a response that is not valid ISAPI XML.",
            str(exc),
        )


def as_list(value: Any) -> list:
    """xmltodict collapses single-element lists; recording counts must not."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def parse_isapi_time(value: str | None) -> datetime | None:
    """Parse ISAPI's ISO-8601 variants, including the trailing-Z form."""
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for pattern in ("%Y%m%dT%H%M%S%z", "%Y%m%dT%H%M%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
        else:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class HikvisionAdapter(VendorAdapter):
    vendor: ClassVar[Vendor] = Vendor.HIKVISION
    family: ClassVar[VendorFamily] = VendorFamily.HIKVISION
    probe_method: ClassVar[ProbeMethod] = ProbeMethod.HIKVISION_ISAPI
    default_http_port: ClassVar[int] = 80
    sdk_port: ClassVar[int | None] = 8000
    capabilities: ClassVar[frozenset] = frozenset(
        {
            _Capability.IDENTIFY,
            _Capability.ENUMERATE_CHANNELS,
            _Capability.ENUMERATE_STORAGE,
            _Capability.READ_CLOCK,
            _Capability.READ_NTP,
            _Capability.SEARCH_RECORDINGS,
            _Capability.DOWNLOAD_RECORDING,
        }
    )
    provenance: ClassVar[str] = (
        "Hikvision ISAPI (Intelligent Security API) over HTTP digest auth. "
        "HCNetSDK is deliberately excluded: its licence forbids redistribution."
    )

    @classmethod
    def fingerprint(cls, client: HttpDeviceClient) -> Fingerprint:
        signals: list[str] = []
        score = 0

        challenge = client.challenge()
        realm_matched = bool(challenge.realm and _MAC_RE.fullmatch(challenge.realm))
        if realm_matched:
            # Hikvision's digest realm is the bare MAC. Dahua prefixes DH_, so a
            # bare 12-hex realm discriminates between the two families pre-auth.
            score += 45
            signals.append(f"digest realm is a bare MAC ({challenge.realm})")

        probe = client.try_get(
            DEVICE_INFO, ProbeMethod.UNAUTHENTICATED_FINGERPRINT, tolerate_auth_failure=True
        )
        if probe is not None and probe.body and "DeviceInfo" in probe.body:
            score += 50
            signals.append(f"{DEVICE_INFO} returned a DeviceInfo document")
        elif realm_matched:
            # Only meaningful once the realm already points at this family: a
            # recorder that authenticates before routing answers 401 for paths it
            # does not serve, so an ungated bonus would score every vendor.
            for artifact in client.artifacts:
                if artifact.endpoint.split("?")[0] == DEVICE_INFO and artifact.status_code == 401:
                    score += 35
                    signals.append(
                        f"{DEVICE_INFO} exists but requires authentication "
                        "(corroborated by the realm)"
                    )
                    break

        return Fingerprint(cls.vendor, score, signals)

    def identify(self, client: HttpDeviceClient) -> StandardizedDevice:
        recorder = EvidenceRecorder(self.probe_method)
        raw: dict[str, Any] = {}

        info_artifact = client.get(DEVICE_INFO, self.probe_method)
        info_doc = parse_isapi_xml(info_artifact.body)
        device_info = info_doc.get("DeviceInfo") or {}
        if not device_info:
            raise AdapterError(
                ErrorCode.PROTOCOL_ERROR,
                "Recorder did not return a DeviceInfo document.",
                "The host answered but does not appear to speak ISAPI.",
            )
        raw[DEVICE_INFO] = device_info

        identity = DeviceIdentity(
            vendor=self.vendor,
            family=self.family,
            confidence=Confidence.CONFIRMED,
            kind=_KIND_MAP.get(
                str(device_info.get("deviceType", "")).upper().replace(" ", ""),
                DeviceKind.UNKNOWN,
            ),
            model_name=device_info.get("model"),
            serial_number=device_info.get("serialNumber"),
            firmware_version=device_info.get("firmwareVersion"),
            firmware_released=device_info.get("firmwareReleasedDate"),
            hardware_version=device_info.get("hardwareVersion"),
            mac_address=device_info.get("macAddress"),
            device_name=device_info.get("deviceName"),
        )

        network = NetworkInfo(
            host=client.host,
            http_port=client.port,
            https_port=443 if client.use_https else None,
            rtsp_port=554,
            sdk_port=self.sdk_port,
            mac_address=device_info.get("macAddress"),
        )

        channels = self._channels(client, raw, recorder)
        storage = self._storage(client, raw, recorder)
        clock = self._clock(client, raw, recorder)

        return StandardizedDevice(
            identity=identity,
            network=network,
            channels=channels,
            storage=storage,
            clock=clock,
            capabilities=sorted(self.capabilities, key=lambda c: c.value),
            evidence=recorder.finish(client),
            raw=raw,
        )

    def _channels(
        self, client: HttpDeviceClient, raw: dict, recorder: EvidenceRecorder
    ) -> list[ChannelInfo]:
        channels: list[ChannelInfo] = []

        analog = client.try_get(VIDEO_INPUT_CHANNELS, self.probe_method)
        if analog is not None:
            doc = parse_isapi_xml(analog.body)
            raw[VIDEO_INPUT_CHANNELS] = doc
            container = doc.get("VideoInputChannelList") or {}
            for entry in as_list(container.get("VideoInputChannel")):
                channel_id = str(entry.get("id", "")).strip()
                if not channel_id:
                    continue
                channels.append(
                    ChannelInfo(
                        channel_id=channel_id,
                        name=entry.get("name"),
                        enabled=to_bool(entry.get("videoInputEnabled")),
                        is_analog=True,
                        resolution=entry.get("resDesc"),
                        track_id=self._track_id(channel_id),
                    )
                )
        else:
            recorder.warn(f"{VIDEO_INPUT_CHANNELS} unavailable; no analog inputs enumerated.")

        digital = client.try_get(INPUT_PROXY_CHANNELS, self.probe_method)
        if digital is not None:
            doc = parse_isapi_xml(digital.body)
            raw[INPUT_PROXY_CHANNELS] = doc
            container = doc.get("InputProxyChannelList") or {}
            for entry in as_list(container.get("InputProxyChannel")):
                channel_id = str(entry.get("id", "")).strip()
                if not channel_id:
                    continue
                channels.append(
                    ChannelInfo(
                        channel_id=channel_id,
                        name=entry.get("name"),
                        enabled=True,
                        is_analog=False,
                        track_id=self._track_id(channel_id),
                    )
                )
        else:
            recorder.warn(f"{INPUT_PROXY_CHANNELS} unavailable; no IP channels enumerated.")

        return channels

    @staticmethod
    def _track_id(channel_id: str) -> str | None:
        """Hikvision track IDs are channel*100 + stream (101 = ch1 main)."""
        number = to_int(channel_id)
        return str(number * 100 + 1) if number else None

    def _storage(
        self, client: HttpDeviceClient, raw: dict, recorder: EvidenceRecorder
    ) -> list[StorageInfo]:
        artifact = client.try_get(STORAGE_HDD, self.probe_method)
        if artifact is None:
            recorder.warn(f"{STORAGE_HDD} unavailable; storage not enumerated.")
            return []

        doc = parse_isapi_xml(artifact.body)
        raw[STORAGE_HDD] = doc
        container = doc.get("hddList") or {}
        disks: list[StorageInfo] = []
        for entry in as_list(container.get("hdd")):
            disks.append(
                StorageInfo(
                    storage_id=str(entry.get("id", "")).strip() or "unknown",
                    name=entry.get("hddName"),
                    kind=entry.get("hddType"),
                    status=entry.get("status"),
                    # ISAPI reports capacity and free space in megabytes.
                    capacity_bytes=mb_to_bytes(entry.get("capacity")),
                    free_bytes=mb_to_bytes(entry.get("freeSpace")),
                    device_property=entry.get("property"),
                )
            )
        return disks

    def _clock(
        self, client: HttpDeviceClient, raw: dict, recorder: EvidenceRecorder
    ) -> ClockInfo:
        clock = ClockInfo(probed_at=datetime.now(timezone.utc))

        artifact = client.try_get(SYSTEM_TIME, self.probe_method)
        if artifact is not None:
            doc = parse_isapi_xml(artifact.body)
            raw[SYSTEM_TIME] = doc
            time_doc = doc.get("Time") or {}
            local_time = time_doc.get("localTime")
            clock.device_time_raw = local_time
            clock.device_time = parse_isapi_time(local_time)
            clock.timezone = time_doc.get("timeZone")
            if clock.device_time and clock.probed_at:
                # Positive drift means the recorder is ahead of the probing host.
                clock.drift_seconds = (clock.device_time - clock.probed_at).total_seconds()
        else:
            recorder.warn(f"{SYSTEM_TIME} unavailable; clock drift could not be measured.")

        ntp = client.try_get(NTP_SERVERS, self.probe_method)
        if ntp is not None:
            doc = parse_isapi_xml(ntp.body)
            raw[NTP_SERVERS] = doc
            container = doc.get("NTPServerList") or {}
            servers: list[str] = []
            enabled: bool | None = None
            for entry in as_list(container.get("NTPServer")):
                address = entry.get("ipAddress") or entry.get("hostName")
                if address:
                    servers.append(str(address))
                flag = to_bool(entry.get("enabled"))
                enabled = flag if enabled is None else (enabled or bool(flag))
            clock.ntp_servers = servers
            clock.ntp_enabled = enabled

        return clock

    def search_recordings(
        self,
        client: HttpDeviceClient,
        channel_ids: list[str],
        start: datetime,
        end: datetime,
        max_results: int = 200,
    ) -> RecordingIndex:
        self.require(_Capability.SEARCH_RECORDINGS)
        tracks = [self._track_id(c) or c for c in channel_ids] or ["101"]
        recordings: list[StandardizedRecording] = []
        warnings: list[str] = []
        truncated = False

        for track in tracks:
            body = self._build_search_request(track, start, end, max_results)
            artifact = client.request(
                "POST",
                CONTENT_SEARCH,
                self.probe_method,
                data=body,
                headers={"Content-Type": "application/xml"},
            )
            if not artifact.status_code or artifact.status_code >= 400:
                warnings.append(f"Search failed for track {track} (HTTP {artifact.status_code}).")
                continue

            doc = parse_isapi_xml(artifact.body)
            result = doc.get("CMSearchResult") or {}
            if str(result.get("responseStatusStrip", "")).upper() == "MORE":
                truncated = True
            match_list = result.get("matchList") or {}
            for item in as_list(match_list.get("searchMatchItem")):
                parsed = self._parse_match(item, track)
                if parsed is not None:
                    recordings.append(parsed)

        return RecordingIndex(
            recordings=recordings,
            searched_span=TimeSpan(start=start, end=end),
            channels_searched=list(channel_ids),
            truncated=truncated,
            warnings=warnings,
        )

    @staticmethod
    def _build_search_request(
        track_id: str, start: datetime, end: datetime, max_results: int
    ) -> str:
        def iso(value: datetime) -> str:
            return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # NOTE: 'searchResultPostion' is misspelled in Hikvision's own API.
        # It must be sent exactly as the device expects it.
        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            "<CMSearchDescription>"
            f"<searchID>{uuid.uuid4()}</searchID>"
            f"<trackIDList><trackID>{track_id}</trackID></trackIDList>"
            "<timeSpanList><timeSpan>"
            f"<startTime>{iso(start)}</startTime>"
            f"<endTime>{iso(end)}</endTime>"
            "</timeSpan></timeSpanList>"
            f"<maxResults>{max_results}</maxResults>"
            "<searchResultPostion>0</searchResultPostion>"
            "</CMSearchDescription>"
        )

    def _parse_match(self, item: dict, track: str) -> StandardizedRecording | None:
        span_doc = item.get("timeSpan") or {}
        start = parse_isapi_time(span_doc.get("startTime"))
        end = parse_isapi_time(span_doc.get("endTime"))
        if start is None or end is None:
            return None

        descriptor = item.get("mediaSegmentDescriptor") or {}
        playback_uri = descriptor.get("playbackURI")
        track_id = str(item.get("trackID") or track)
        return StandardizedRecording(
            recording_id=str(item.get("sourceID") or f"{track}-{start.isoformat()}"),
            # Hikvision indexes by track, but the rest of the pipeline joins on
            # channel, so the track is decomposed back into its channel here and
            # retained separately rather than leaking into channel_id.
            channel_id=self._channel_from_track(track_id),
            track_id=track_id,
            span=TimeSpan(start=start, end=end),
            codec=descriptor.get("codecType"),
            # Hikvision embeds the exact byte length in the playback URI, which
            # gives acquisition a length to verify against before hashing.
            size_bytes=self._size_from_uri(playback_uri),
            playback_uri=playback_uri,
            source_method=self.probe_method,
            raw=item,
        )

    @staticmethod
    def _channel_from_track(track_id: str) -> str:
        """Recover the channel number from a Hikvision track id (101 -> 1)."""
        number = to_int(track_id)
        if number is None:
            return track_id
        return str(number // 100) if number >= 100 else str(number)

    @staticmethod
    def _size_from_uri(uri: str | None) -> int | None:
        if not uri:
            return None
        try:
            values = parse_qs(urlparse(uri).query).get("size")
            return to_int(values[0]) if values else None
        except ValueError:
            return None

    def download_recording(
        self,
        client: HttpDeviceClient,
        destination: str,
        recording_id: str,
        channel_id: str,
        start: datetime,
        end: datetime,
        playback_uri: str | None = None,
        file_path: str | None = None,
    ) -> AcquisitionResult:
        """Export one segment via ISAPI's controlled-download endpoint.

        The playback URI returned by the recording search is echoed back
        verbatim; deriving it independently risks requesting a different
        segment from the one that was indexed.
        """
        self.require(_Capability.DOWNLOAD_RECORDING)
        if not playback_uri:
            raise AdapterError(
                ErrorCode.PROTOCOL_ERROR,
                "A playback URI from the recording index is required to acquire this segment.",
                "Run a recording search first and pass through its playbackURI.",
            )

        started = datetime.now(timezone.utc)
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            "<downloadRequest>"
            f"<playbackURI>{playback_uri}</playbackURI>"
            "</downloadRequest>"
        )
        written, md5, sha256 = client.stream_to_file(
            "POST",
            CONTENT_DOWNLOAD,
            destination,
            data=body,
            headers={"Content-Type": "application/xml"},
        )
        finished = datetime.now(timezone.utc)

        warnings: list[str] = []
        expected = self._size_from_uri(playback_uri)
        if expected is not None and expected != written:
            # The index advertises an exact byte length; a mismatch means the
            # export is not the segment that was indexed.
            warnings.append(
                f"Recorder advertised {expected} bytes but {written} were received."
            )

        return AcquisitionResult(
            recording_id=recording_id,
            channel_id=channel_id,
            span=TimeSpan(start=start, end=end),
            stored_path=destination,
            size_bytes=written,
            md5=md5,
            sha256=sha256,
            container="MPEG-PS (Hikvision IMKH)",
            acquired_at=started,
            duration_ms=int((finished - started).total_seconds() * 1000),
            source_uri=playback_uri,
            warnings=warnings,
        )

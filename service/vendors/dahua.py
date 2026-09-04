"""Dahua adapter, speaking the HTTP CGI API with digest authentication.

Field names and the media-search lifecycle follow Dahua's published
"API of HTTP Protocol Specification". The NetSDK is deliberately excluded: its
licence forbids decomposing or embedding the software, so this adapter is a
clean-room implementation over the documented CGI surface.

The GPL-2.0 ``amcrest`` package covers similar ground but its copyleft would be
viral for a distributable forensics product, so it is not a dependency.

This class is also the base for CP Plus, whose recorders run Dahua firmware.
"""

import re
from datetime import datetime, timezone
from typing import Any, ClassVar

from models.common import (
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
    Capability,
    EvidenceRecorder,
    Fingerprint,
    VendorAdapter,
    to_int,
)
from vendors.transports.http_digest import HttpDeviceClient

_INDEX_RE = re.compile(r"^(?P<name>[^\[\]]+)\[(?P<index>\d+)\]$")
_DAHUA_REALM_RE = re.compile(r"^DH_[0-9A-Fa-f]{12}$")

MAGICBOX = "/cgi-bin/magicBox.cgi"
GLOBAL_CGI = "/cgi-bin/global.cgi"
CONFIG_MANAGER = "/cgi-bin/configManager.cgi"
STORAGE_DEVICE = "/cgi-bin/storageDevice.cgi"
DEV_VIDEO_INPUT = "/cgi-bin/devVideoInput.cgi"
MEDIA_FILE_FIND = "/cgi-bin/mediaFileFind.cgi"
LOADFILE = "/cgi-bin/RPC_Loadfile"

#: Checked in order. CP Plus rebadges use their own model prefixes (CP-UNR-...
#: for network recorders, CP-UVR-... for analog), which contain none of the
#: generic tokens, so they are matched explicitly.
_KIND_HINTS = (
    ("HCVR", DeviceKind.HVR),
    ("NVR", DeviceKind.NVR),
    ("XVR", DeviceKind.XVR),
    ("DVR", DeviceKind.DVR),
    ("CP-UNR", DeviceKind.NVR),
    ("CP-UVR", DeviceKind.DVR),
    ("CP-UAR", DeviceKind.DVR),
    ("IPC", DeviceKind.IPC),
)


def parse_kv(body: str) -> dict[str, Any]:
    """Parse Dahua's flat ``key=value`` responses into a nested structure.

    Dahua encodes structure in the key rather than the body, using dotted paths
    and bracketed indices::

        serialNumber=YZC4CS1PAJE7A5D
        items[0].Channel=1
        table.NTP.Address=clock.isc.org

    Indexed segments become lists, dotted segments become nested dicts.
    """
    root: dict[str, Any] = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        _assign(root, key.strip(), value.strip())
    return root


def _assign(root: dict[str, Any], key: str, value: str) -> None:
    segments = key.split(".")
    cursor: Any = root
    for position, segment in enumerate(segments):
        is_last = position == len(segments) - 1
        match = _INDEX_RE.match(segment)
        if match:
            name = match.group("name")
            index = int(match.group("index"))
            bucket = cursor.setdefault(name, []) if isinstance(cursor, dict) else None
            if not isinstance(bucket, list):
                return
            while len(bucket) <= index:
                bucket.append({})
            if is_last:
                bucket[index] = value
            else:
                if not isinstance(bucket[index], dict):
                    bucket[index] = {}
                cursor = bucket[index]
        else:
            if not isinstance(cursor, dict):
                return
            if is_last:
                cursor[segment] = value
            else:
                nxt = cursor.get(segment)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cursor[segment] = nxt
                cursor = nxt


def _as_utc_text(value: datetime) -> str:
    """Render an instant as the recorder's expected wall-clock string, in UTC.

    Dahua reports and accepts local wall-clock with no zone attached. Sending
    UTC consistently means the window is at least reproducible; the measured
    clock offset is applied at normalization time rather than being folded into
    the query, so the recorder's own index stays comparable to its exports.
    """
    moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def parse_dahua_time(value: str | None) -> datetime | None:
    """Dahua reports wall-clock local time as ``Y-M-D H:M:S`` with no zone."""
    if not value:
        return None
    text = value.strip()
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H-%M-%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


class DahuaAdapter(VendorAdapter):
    vendor: ClassVar[Vendor] = Vendor.DAHUA
    family: ClassVar[VendorFamily] = VendorFamily.DAHUA
    probe_method: ClassVar[ProbeMethod] = ProbeMethod.DAHUA_CGI
    default_http_port: ClassVar[int] = 80
    sdk_port: ClassVar[int | None] = 37777
    capabilities: ClassVar[frozenset] = frozenset(
        {
            Capability.IDENTIFY,
            Capability.ENUMERATE_CHANNELS,
            Capability.ENUMERATE_STORAGE,
            Capability.READ_CLOCK,
            Capability.READ_NTP,
            Capability.SEARCH_RECORDINGS,
            Capability.DOWNLOAD_RECORDING,
        }
    )
    provenance: ClassVar[str] = (
        "Dahua HTTP CGI API over digest auth. NetSDK excluded on licence grounds; "
        "clean-room implementation of the documented CGI surface."
    )

    @classmethod
    def fingerprint(cls, client: HttpDeviceClient) -> Fingerprint:
        signals: list[str] = []
        score = 0

        challenge = client.challenge()
        realm_matched = bool(challenge.realm and _DAHUA_REALM_RE.fullmatch(challenge.realm))
        if realm_matched:
            # Dahua's digest realm is DH_ followed by the MAC, which separates
            # it from Hikvision's bare-MAC realm before any credential is sent.
            score += 45
            signals.append(f"digest realm uses the DH_ prefix ({challenge.realm})")

        probe = client.try_get(
            MAGICBOX,
            ProbeMethod.UNAUTHENTICATED_FINGERPRINT,
            tolerate_auth_failure=True,
            action="getSystemInfo",
        )
        if probe is not None and ("deviceType=" in probe.body or "serialNumber=" in probe.body):
            score += 50
            signals.append("magicBox.cgi returned a system-info key/value document")
        elif realm_matched:
            # Gated for the same reason as the Hikvision branch: a recorder that
            # authenticates before routing 401s every path, real or not.
            for artifact in client.artifacts:
                # Endpoints are labelled with their query string, so compare the
                # path portion rather than the whole label.
                if artifact.endpoint.split("?")[0] == MAGICBOX and artifact.status_code == 401:
                    score += 35
                    signals.append(
                        "magicBox.cgi exists but requires authentication "
                        "(corroborated by the realm)"
                    )
                    break

        return Fingerprint(cls.vendor, score, signals)

    def identify(self, client: HttpDeviceClient) -> StandardizedDevice:
        recorder = EvidenceRecorder(self.probe_method)
        raw: dict[str, Any] = {}

        info = client.get(MAGICBOX, self.probe_method, action="getSystemInfo")
        system = parse_kv(info.body)
        if not system:
            raise AdapterError(
                ErrorCode.PROTOCOL_ERROR,
                "Recorder did not return a parsable magicBox system-info document.",
                "The host answered but does not appear to speak the Dahua CGI API.",
            )
        raw["magicBox.getSystemInfo"] = system

        # getSystemInfo and getSerialNo disagree on the key name for the same
        # value ('serialNumber' vs 'sn'), so both are consulted.
        serial = system.get("serialNumber")
        if not serial:
            serial_artifact = client.try_get(
                MAGICBOX, self.probe_method, action="getSerialNo"
            )
            if serial_artifact is not None:
                parsed = parse_kv(serial_artifact.body)
                raw["magicBox.getSerialNo"] = parsed
                serial = parsed.get("sn")

        software = client.try_get(MAGICBOX, self.probe_method, action="getSoftwareVersion")
        firmware = None
        if software is not None:
            parsed = parse_kv(software.body)
            raw["magicBox.getSoftwareVersion"] = parsed
            firmware = parsed.get("version")

        machine = client.try_get(MAGICBOX, self.probe_method, action="getMachineName")
        device_name = None
        if machine is not None:
            parsed = parse_kv(machine.body)
            raw["magicBox.getMachineName"] = parsed
            device_name = parsed.get("name") or parsed.get("machineName")

        device_type = system.get("deviceType") or system.get("type")
        identity = DeviceIdentity(
            vendor=self.vendor,
            family=self.family,
            confidence=Confidence.CONFIRMED,
            kind=self._kind_from_type(device_type),
            model_name=device_type,
            serial_number=serial,
            firmware_version=firmware or system.get("version"),
            hardware_version=system.get("hardwareVersion"),
            mac_address=self._mac(client),
            device_name=device_name,
        )

        network = NetworkInfo(
            host=client.host,
            http_port=client.port,
            https_port=443 if client.use_https else None,
            rtsp_port=554,
            sdk_port=self.sdk_port,
            mac_address=identity.mac_address,
        )

        return StandardizedDevice(
            identity=identity,
            network=network,
            channels=self._channels(client, raw, recorder),
            storage=self._storage(client, raw, recorder),
            clock=self._clock(client, raw, recorder),
            capabilities=sorted(self.capabilities, key=lambda c: c.value),
            evidence=recorder.finish(client),
            raw=raw,
        )

    @staticmethod
    def _kind_from_type(device_type: str | None) -> DeviceKind:
        if not device_type:
            return DeviceKind.UNKNOWN
        upper = device_type.upper()
        for token, kind in _KIND_HINTS:
            if token in upper:
                return kind
        return DeviceKind.UNKNOWN

    @staticmethod
    def _mac(client: HttpDeviceClient) -> str | None:
        """Recover the MAC from the digest realm when the CGI omits it."""
        realm_mac = client.challenge().realm_mac
        if not realm_mac:
            return None
        return ":".join(realm_mac[i : i + 2] for i in range(0, 12, 2)).lower()

    def _channels(
        self, client: HttpDeviceClient, raw: dict, recorder: EvidenceRecorder
    ) -> list[ChannelInfo]:
        artifact = client.try_get(DEV_VIDEO_INPUT, self.probe_method, action="getCollect")
        if artifact is None:
            recorder.warn(
                f"{DEV_VIDEO_INPUT}?action=getCollect unavailable; channels not enumerated."
            )
            return []

        parsed = parse_kv(artifact.body)
        raw["devVideoInput.getCollect"] = parsed
        entries = parsed.get("channels") or parsed.get("items") or []
        channels: list[ChannelInfo] = []
        if isinstance(entries, list):
            for index, entry in enumerate(entries, start=1):
                detail = entry if isinstance(entry, dict) else {}
                channels.append(
                    ChannelInfo(
                        channel_id=str(detail.get("Channel") or index),
                        name=detail.get("Name"),
                        enabled=True,
                        is_analog=None,
                        track_id=str(detail.get("Channel") or index),
                    )
                )
        if not channels:
            recorder.warn("Recorder reported no video input channels.")
        return channels

    def _storage(
        self, client: HttpDeviceClient, raw: dict, recorder: EvidenceRecorder
    ) -> list[StorageInfo]:
        artifact = client.try_get(STORAGE_DEVICE, self.probe_method, action="getDeviceAllInfo")
        if artifact is None:
            recorder.warn(f"{STORAGE_DEVICE} unavailable; storage not enumerated.")
            return []

        parsed = parse_kv(artifact.body)
        raw["storageDevice.getDeviceAllInfo"] = parsed
        entries = parsed.get("list") or parsed.get("items") or []
        disks: list[StorageInfo] = []
        if isinstance(entries, list):
            for index, entry in enumerate(entries):
                detail = entry if isinstance(entry, dict) else {}
                detail_block = detail.get("Detail")
                if isinstance(detail_block, list) and detail_block:
                    inner = detail_block[0] if isinstance(detail_block[0], dict) else {}
                else:
                    inner = detail
                # Dahua reports these figures in megabytes.
                total = to_int(inner.get("TotalBytes") or inner.get("Total"))
                used = to_int(inner.get("UsedBytes") or inner.get("Used"))
                capacity = total * 1024 * 1024 if total is not None else None
                free = (
                    (total - used) * 1024 * 1024
                    if total is not None and used is not None
                    else None
                )
                disks.append(
                    StorageInfo(
                        storage_id=str(detail.get("Name") or index),
                        name=detail.get("Name") or inner.get("Path"),
                        kind=inner.get("Type"),
                        status=inner.get("State") or detail.get("State"),
                        capacity_bytes=capacity,
                        free_bytes=free,
                        device_property=inner.get("Attribute"),
                    )
                )
        return disks

    def _clock(
        self, client: HttpDeviceClient, raw: dict, recorder: EvidenceRecorder
    ) -> ClockInfo:
        clock = ClockInfo(probed_at=datetime.now(timezone.utc))

        artifact = client.try_get(GLOBAL_CGI, self.probe_method, action="getCurrentTime")
        if artifact is not None:
            parsed = parse_kv(artifact.body)
            raw["global.getCurrentTime"] = parsed
            reported = parsed.get("result") or parsed.get("time")
            clock.device_time_raw = reported
            clock.device_time = parse_dahua_time(reported)
            if clock.device_time and clock.probed_at:
                clock.drift_seconds = (clock.device_time - clock.probed_at).total_seconds()
        else:
            recorder.warn("global.cgi getCurrentTime unavailable; clock drift not measured.")

        ntp = client.try_get(CONFIG_MANAGER, self.probe_method, action="getConfig", name="NTP")
        if ntp is not None:
            parsed = parse_kv(ntp.body)
            raw["configManager.NTP"] = parsed
            block = (parsed.get("table") or {}).get("NTP") or {}
            address = block.get("Address")
            clock.ntp_servers = [str(address)] if address else []
            enabled = str(block.get("Enable", "")).lower()
            clock.ntp_enabled = True if enabled == "true" else False if enabled == "false" else None
            clock.timezone = block.get("TimeZone")

        return clock

    def search_recordings(
        self,
        client: HttpDeviceClient,
        channel_ids: list[str],
        start: datetime,
        end: datetime,
        max_results: int = 200,
    ) -> RecordingIndex:
        self.require(Capability.SEARCH_RECORDINGS)
        targets = channel_ids or ["1"]
        recordings: list[StandardizedRecording] = []
        warnings: list[str] = []
        truncated = False

        for channel in targets:
            found, was_truncated, channel_warnings = self._search_channel(
                client, channel, start, end, max_results
            )
            recordings.extend(found)
            truncated = truncated or was_truncated
            warnings.extend(channel_warnings)

        return RecordingIndex(
            recordings=recordings,
            searched_span=TimeSpan(start=start, end=end),
            channels_searched=list(targets),
            truncated=truncated,
            warnings=warnings,
        )

    def _search_channel(
        self,
        client: HttpDeviceClient,
        channel: str,
        start: datetime,
        end: datetime,
        max_results: int,
    ) -> tuple[list[StandardizedRecording], bool, list[str]]:
        """Run Dahua's five-step find lifecycle for one channel.

        The device allocates a finder object that must be closed and destroyed
        even when the search fails, or the handle leaks on the recorder.
        """
        warnings: list[str] = []
        created = client.try_get(MEDIA_FILE_FIND, self.probe_method, action="factory.create")
        if created is None:
            return [], False, [f"Could not create a finder object for channel {channel}."]

        handle = parse_kv(created.body).get("result")
        if not handle:
            return [], False, [f"Recorder returned no finder handle for channel {channel}."]

        found: list[StandardizedRecording] = []
        truncated = False
        try:
            started = client.try_get(
                MEDIA_FILE_FIND,
                self.probe_method,
                action="findFile",
                object=handle,
                **{
                    "condition.Channel": channel,
                    # Normalised to UTC to match the Hikvision adapter, so the
                    # same instant produces the same query across families.
                    "condition.StartTime": _as_utc_text(start),
                    "condition.EndTime": _as_utc_text(end),
                },
            )
            if started is None:
                warnings.append(
                    f"Channel {channel}: findFile was refused, so this channel's index "
                    f"was never read. Absence of footage cannot be inferred."
                )
                return [], False, warnings

            remaining = max_results
            while remaining > 0:
                # The device caps each batch at 100 regardless of what we ask.
                batch = min(remaining, 100)
                page = client.try_get(
                    MEDIA_FILE_FIND,
                    self.probe_method,
                    action="findNextFile",
                    object=handle,
                    count=batch,
                )
                if page is None:
                    # The recorder refused the query. Reporting this as a clean
                    # empty result would present "no footage exists" when the
                    # truth is "we were not told", which is the one conclusion a
                    # forensic index must never invite.
                    warnings.append(
                        f"Channel {channel}: the recorder refused findNextFile, so its "
                        f"index was only partially read. Results for this channel are "
                        f"incomplete and absence of footage cannot be inferred."
                    )
                    break
                parsed = parse_kv(page.body)
                count = to_int(parsed.get("found")) or 0
                items = parsed.get("items") or []
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            record = self._parse_item(item, channel)
                            if record is not None:
                                found.append(record)
                if count < batch:
                    break
                remaining -= batch
                if remaining <= 0:
                    truncated = True
        finally:
            # Always release the finder, even on an early return or exception.
            client.try_get(MEDIA_FILE_FIND, self.probe_method, action="close", object=handle)
            client.try_get(MEDIA_FILE_FIND, self.probe_method, action="destroy", object=handle)

        return found, truncated, warnings

    def _parse_item(self, item: dict, channel: str) -> StandardizedRecording | None:
        start = parse_dahua_time(item.get("StartTime"))
        end = parse_dahua_time(item.get("EndTime"))
        if start is None or end is None:
            return None
        file_path = item.get("FilePath")
        return StandardizedRecording(
            recording_id=str(file_path or f"{channel}-{start.isoformat()}"),
            channel_id=str(item.get("Channel") or channel),
            span=TimeSpan(start=start, end=end),
            codec=item.get("Type"),
            size_bytes=to_int(item.get("Length")),
            file_path=file_path,
            event_type=self._first_event(item.get("Events")),
            # The CGI encodes this as items[0].Flags[0]=Timing, so parse_kv yields
            # a list; the previous str-only guard meant it was never populated.
            record_trigger=self._first_value(item.get("Flags")),
            # Overwrite count speaks directly to retention and wipe reasoning.
            overwrite_count=to_int(item.get("Overwrites")),
            source_method=self.probe_method,
            raw=item,
        )

    @staticmethod
    def _first_value(value: Any) -> str | None:
        """First entry of a Dahua indexed field, which may arrive as a bare string."""
        if isinstance(value, list):
            return str(value[0]) if value else None
        return str(value) if isinstance(value, str) and value else None

    @staticmethod
    def _first_event(events: Any) -> str | None:
        return DahuaAdapter._first_value(events)

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
        """Export one segment via the RPC_Loadfile path.

        Dahua addresses recordings by their on-device path (as returned by
        ``mediaFileFind``), not by a playback URI, so the indexed FilePath is
        the required input here.
        """
        self.require(Capability.DOWNLOAD_RECORDING)
        target = file_path or recording_id
        if not target or not target.startswith("/"):
            raise AdapterError(
                ErrorCode.PROTOCOL_ERROR,
                "An on-device file path from the recording index is required to acquire this segment.",
                "Run a recording search first and pass through its FilePath.",
            )

        started = datetime.now(timezone.utc)
        written, md5, sha256 = client.stream_to_file("GET", f"{LOADFILE}{target}", destination)
        finished = datetime.now(timezone.utc)

        return AcquisitionResult(
            recording_id=recording_id,
            channel_id=channel_id,
            span=TimeSpan(start=start, end=end),
            stored_path=destination,
            size_bytes=written,
            md5=md5,
            sha256=sha256,
            container="DHAV",
            acquired_at=started,
            duration_ms=int((finished - started).total_seconds() * 1000),
            source_uri=f"{LOADFILE}{target}",
            warnings=[],
        )

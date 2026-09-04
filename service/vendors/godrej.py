"""Godrej adapter, speaking DVRIP against XiongMai-lineage recorders.

Godrej Security Solutions does not manufacture its recorder firmware and
publishes no SDK, no API documentation and no ONVIF conformance. The protocol
attribution here rests on device fingerprints reported for Godrej-badged units
(DVRIP on TCP 34567, the 192.168.1.10 default address, the admin/guest default
account pair and the XiongMai "Net Service" menu), which point at XiongMai
white-label hardware.

That evidence is circumstantial, so this adapter never reports better than
PROBABLE confidence and says why in the evidence record. Godrej also ships
multiple hardware generations, so a unit that does not answer DVRIP is a
plausible outcome rather than a bug - it is reported as UNSUPPORTED with the
fingerprint that was actually observed.
"""

from datetime import datetime, timezone
from typing import Any, ClassVar

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
    ProbeEvidence,
    StandardizedDevice,
    StorageInfo,
)
from vendors.base import AdapterError, EvidenceRecorder, Fingerprint, VendorAdapter, to_int
from vendors.transports.dvrip import DEFAULT_PORT, DvripClient, port_open
from vendors.transports.http_digest import HttpDeviceClient, TransportError


def _parse_dvrip_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class GodrejAdapter(VendorAdapter):
    vendor: ClassVar[Vendor] = Vendor.GODREJ
    family: ClassVar[VendorFamily] = VendorFamily.XIONGMAI
    probe_method: ClassVar[ProbeMethod] = ProbeMethod.XIONGMAI_DVRIP
    default_http_port: ClassVar[int] = 80
    sdk_port: ClassVar[int | None] = DEFAULT_PORT
    capabilities: ClassVar[frozenset] = frozenset(
        {
            Capability.IDENTIFY,
            Capability.ENUMERATE_CHANNELS,
            Capability.ENUMERATE_STORAGE,
            Capability.READ_CLOCK,
        }
    )
    #: Attribution rests on device fingerprints, never on vendor documentation,
    #: so no detection score may promote this past PROBABLE.
    max_confidence: ClassVar[Confidence] = Confidence.PROBABLE
    provenance: ClassVar[str] = (
        "Godrej recorders are white-labelled XiongMai hardware speaking DVRIP on "
        "TCP 34567. Godrej publishes no SDK, API documentation or ONVIF conformance, "
        "so support is fingerprint-derived and reported at PROBABLE confidence."
    )

    @classmethod
    def fingerprint(cls, client: HttpDeviceClient) -> Fingerprint:
        """Detect the DVRIP service rather than an HTTP surface.

        A listening 34567 is the discriminator: neither the Hikvision nor the
        Dahua family uses that port.
        """
        signals: list[str] = []
        score = 0

        port = client.sdk_port or DEFAULT_PORT
        if port_open(client.host, port, timeout=min(client.timeout, 3.0)):
            score += 55
            signals.append(f"TCP {port} (DVRIP) is open")

            try:
                with DvripClient(
                    client.host,
                    port,
                    client.username or "admin",
                    client.password or "",
                    timeout=client.timeout,
                ) as probe:
                    probe.login()
                    score += 30
                    signals.append("DVRIP login handshake accepted")
            except TransportError as exc:
                if exc.code == ErrorCode.AUTH_FAILED:
                    # Speaking DVRIP at all is the vendor signal; wrong
                    # credentials still confirm the protocol family.
                    score += 20
                    signals.append("DVRIP service answered the login handshake")
                else:
                    signals.append(f"DVRIP handshake did not complete: {exc.message}")

        return Fingerprint(cls.vendor, score, signals)

    def identify(self, client: HttpDeviceClient) -> StandardizedDevice:
        """Identify over DVRIP.

        The shared adapter interface hands every adapter an HTTP client. This
        family does not use HTTP, so the connection details are taken from it
        and a DVRIP session is opened instead.
        """
        recorder = EvidenceRecorder(self.probe_method)
        raw: dict[str, Any] = {}

        port = client.sdk_port or DEFAULT_PORT
        with DvripClient(
            client.host,
            port,
            client.username or "admin",
            client.password or "",
            timeout=client.timeout,
        ) as session:
            session.login()

            info_response = session.get_info("SystemInfo")
            system = info_response.get("SystemInfo") or {}
            if not system:
                raise AdapterError(
                    ErrorCode.PROTOCOL_ERROR,
                    "Recorder accepted DVRIP login but returned no SystemInfo block.",
                    "The device may be a XiongMai generation this adapter does not cover.",
                )
            raw["dvrip.SystemInfo"] = info_response

            identity = DeviceIdentity(
                vendor=self.vendor,
                family=self.family,
                # Attribution is fingerprint-derived, never vendor-confirmed.
                confidence=Confidence.PROBABLE,
                kind=DeviceKind.DVR,
                model_name=system.get("HardWare"),
                serial_number=system.get("SerialNo"),
                firmware_version=system.get("SoftWareVersion"),
                firmware_released=system.get("BuildTime"),
                hardware_version=system.get("HardWareVersion"),
                mac_address=None,
                device_name=None,
            )

            network = NetworkInfo(
                host=client.host,
                http_port=client.port,
                rtsp_port=554,
                sdk_port=port,
            )

            channels = self._channels(system)
            storage = self._storage(session, raw, recorder)
            clock = self._clock(session, raw, recorder)

            evidence = ProbeEvidence(
                method=self.probe_method,
                started_at=recorder.started_at,
                finished_at=datetime.now(timezone.utc),
                duration_ms=int(
                    (datetime.now(timezone.utc) - recorder.started_at).total_seconds() * 1000
                ),
                endpoints_attempted=list(session.attempted),
                endpoints_succeeded=list(session.succeeded),
                warnings=recorder.warnings
                + [
                    "Vendor attribution is inferred from device fingerprints; Godrej "
                    "publishes no protocol documentation."
                ],
                artifacts=list(session.artifacts),
            )

        return StandardizedDevice(
            identity=identity,
            network=network,
            channels=channels,
            storage=storage,
            clock=clock,
            capabilities=sorted(self.capabilities, key=lambda c: c.value),
            evidence=evidence,
            raw=raw,
        )

    @staticmethod
    def _channels(system: dict) -> list[ChannelInfo]:
        """DVRIP reports channel counts, not per-channel records.

        Analog and digital inputs are counted separately, so both are expanded
        and tagged rather than merged into an untyped total.
        """
        channels: list[ChannelInfo] = []
        analog_count = to_int(system.get("VideoInChannel")) or 0
        digital_count = to_int(system.get("DigChannel")) or 0

        for index in range(1, analog_count + 1):
            channels.append(
                ChannelInfo(
                    channel_id=str(index), enabled=True, is_analog=True, track_id=str(index)
                )
            )
        for offset in range(1, digital_count + 1):
            index = analog_count + offset
            channels.append(
                ChannelInfo(
                    channel_id=str(index), enabled=True, is_analog=False, track_id=str(index)
                )
            )
        return channels

    def _storage(
        self, session: DvripClient, raw: dict, recorder: EvidenceRecorder
    ) -> list[StorageInfo]:
        try:
            response = session.get_info("StorageInfo")
        except TransportError as exc:
            recorder.warn(f"StorageInfo query failed: {exc.message}")
            return []

        raw["dvrip.StorageInfo"] = response
        blocks = response.get("StorageInfo") or []
        disks: list[StorageInfo] = []

        # StorageInfo nests as a list of lists of partition records and the depth
        # varies by firmware, so it is flattened defensively. Firmware that
        # repeats a figure at both the disk and partition level must not be
        # counted twice: when a node carries partitions, only the partitions are
        # recorded, because summing both doubles the reported capacity.
        def walk(node: Any) -> None:
            if isinstance(node, list):
                for child in node:
                    walk(child)
                return
            if not isinstance(node, dict):
                return

            partitions = node.get("Partition")
            if isinstance(partitions, list) and partitions:
                walk(partitions)
                return

            if "TotalSpace" in node or "RemainSpace" in node:
                total = to_int(node.get("TotalSpace"))
                remain = to_int(node.get("RemainSpace"))
                disks.append(
                    StorageInfo(
                        storage_id=str(node.get("LogicSerialNo") or len(disks)),
                        name=node.get("Name") or node.get("LogicSerialNo"),
                        kind=None,
                        status=node.get("Status"),
                        # DVRIP reports these figures in megabytes.
                        capacity_bytes=total * 1024 * 1024 if total is not None else None,
                        free_bytes=remain * 1024 * 1024 if remain is not None else None,
                        device_property=None,
                    )
                )
                return

            for child in node.values():
                walk(child)

        walk(blocks)
        if not disks:
            recorder.warn("StorageInfo returned no recognizable partition records.")
        return disks

    def _clock(self, session: DvripClient, raw: dict, recorder: EvidenceRecorder) -> ClockInfo:
        clock = ClockInfo(probed_at=datetime.now(timezone.utc))
        try:
            response = session.get_time()
        except TransportError as exc:
            recorder.warn(f"Clock query failed: {exc.message}")
            return clock

        raw["dvrip.OPTimeQuery"] = response
        reported = response.get("OPTimeQuery")
        clock.device_time_raw = reported if isinstance(reported, str) else None
        clock.device_time = _parse_dvrip_time(clock.device_time_raw)
        if clock.device_time and clock.probed_at:
            clock.drift_seconds = (clock.device_time - clock.probed_at).total_seconds()
        return clock

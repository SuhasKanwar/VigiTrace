"use client";

import { ArrowLeft, BrainCircuit, Fingerprint, FileSearch, RotateCcw, ScanSearch, Trash2, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { CapabilityChip, ConfidenceBadge, ConfidenceNote, STATE_NOTE, SeverityBadge, StateBadge, VendorBadge } from "@/components/devices/badges";
import CustodyTimeline from "@/components/devices/custody-timeline";
import RecordingsPanel from "@/components/devices/recordings-panel";
import { ActionButton, BUTTON, EYEBROW_MUTED, ErrorPanel, Field, FieldGrid, LoadingPanel, PageHeader, PageShell, Panel, TABLE_CELL, TABLE_HEAD, TableScroll } from "@/components/devices/ui";
import { deleteDevice, detectDevice, getDevice, identifyDevice, runAnalysis } from "@/lib/devices/api";
import { EMPTY_VALUE, formatBoolean, formatBytes, formatDrift, formatDuration, formatEndpoint, formatRelative, formatTimestamp, formatValue, isDriftOutOfTolerance } from "@/lib/devices/format";
import useResource from "@/lib/devices/use-resource";
import { CLOCK_DRIFT_LIMIT_SECONDS, KNOWN_CAPABILITIES, type AnalysisReport, type DetectionResult, type DeviceStorageVolume } from "@/lib/devices/types";

function usedRatio(volume: DeviceStorageVolume): number | null {
    if (volume.capacityBytes === null || volume.capacityBytes <= 0 || volume.usedBytes === null) return null;
    return Math.min(Math.max(volume.usedBytes / volume.capacityBytes, 0), 1);
}

export default function DeviceDetail({ deviceId }: { deviceId: string }) {
    const router = useRouter();
    const load = useCallback(() => getDevice(deviceId), [deviceId]);
    const { data: device, error, loading, reload, setData } = useResource(load);

    const [detection, setDetection] = useState<DetectionResult | null>(null);
    const [analysis, setAnalysis] = useState<AnalysisReport | null>(null);
    const [detecting, setDetecting] = useState(false);
    const [identifying, setIdentifying] = useState(false);
    const [analysing, setAnalysing] = useState(false);
    const [removing, setRemoving] = useState(false);
    const [confirmRemoval, setConfirmRemoval] = useState(false);
    const busy = detecting || identifying || analysing || removing;

    async function detect() {
        setDetecting(true);
        try {
            setDetection(await detectDevice(deviceId));
            await reload();
        } catch {
            // Already surfaced by the response interceptor.
        } finally {
            setDetecting(false);
        }
    }

    async function identify() {
        setIdentifying(true);
        try {
            setData(await identifyDevice(deviceId));
        } catch {
            // Already surfaced by the response interceptor.
        } finally {
            setIdentifying(false);
        }
    }

    async function analyse() {
        setAnalysing(true);
        try {
            setAnalysis(await runAnalysis(deviceId));
            document.getElementById("analysis")?.scrollIntoView({ behavior: "smooth", block: "start" });
        } catch {
            // Already surfaced by the response interceptor.
        } finally {
            setAnalysing(false);
        }
    }

    async function remove() {
        setRemoving(true);
        try {
            await deleteDevice(deviceId);
            router.push("/dashboard/devices");
            router.refresh();
        } catch {
            setRemoving(false);
            setConfirmRemoval(false);
        }
    }

    if (loading && device === null) {
        return <PageShell><LoadingPanel label="Loading device record" /></PageShell>;
    }

    if (error || device === null) {
        return (
            <PageShell>
                <PageHeader actions={<Link className={BUTTON.secondary} href="/dashboard/devices"><ArrowLeft aria-hidden="true" className="size-4" />Back to devices</Link>} eyebrow="Device record" title="Device unavailable" />
                <div className="mt-8"><ErrorPanel message={error ?? "This device record could not be read."} onRetry={() => void reload()} title="Device record could not be read" /></div>
            </PageShell>
        );
    }

    const { identity, network, clock } = device;
    const driftCritical = isDriftOutOfTolerance(clock.driftSeconds);

    return (
        <PageShell>
            <PageHeader
                actions={<><ActionButton Icon={ScanSearch} disabled={busy} onClick={() => void detect()} pending={detecting} title="Fingerprint the recorder without authenticating">Detect</ActionButton><ActionButton Icon={Fingerprint} disabled={busy} onClick={() => void identify()} pending={identifying} title="Authenticate and read identity, channels, storage, and clock">Identify</ActionButton><a className={BUTTON.secondary} href="#recordings"><FileSearch aria-hidden="true" className="size-4" />Search recordings</a><ActionButton Icon={BrainCircuit} disabled={busy} onClick={() => void analyse()} pending={analysing} variant="primary">Run analysis</ActionButton></>}
                description={STATE_NOTE[device.state]}
                eyebrow="Device record"
                title={device.name}
            />

            <div className="mt-6 flex flex-wrap items-center gap-3 border-b border-(--border-color) pb-6">
                <StateBadge state={device.state} />
                <VendorBadge family={identity.family} vendor={identity.vendor} />
                <ConfidenceBadge confidence={identity.confidence} />
                <span className="font-mono text-xs text-(--secondary-text-color)">{formatEndpoint(device)}</span>
                <span className="text-xs text-(--secondary-text-color)">{device.channelCount} channel{device.channelCount === 1 ? "" : "s"}</span>
                <span className="text-xs text-(--secondary-text-color)" title={formatTimestamp(device.lastProbedAt)}>Probed {formatRelative(device.lastProbedAt)}</span>
                <ActionButton Icon={RotateCcw} onClick={() => void reload()} pending={loading} variant="ghost">Refresh</ActionButton>
            </div>

            <div className="mt-8 space-y-8">
                <ConfidenceNote confidence={identity.confidence} />

                {detection ? (
                    <Panel description="Unauthenticated fingerprint. It narrows the field; it does not establish the vendor." eyebrow="Latest detection" title="Detection result">
                        <FieldGrid>
                            <Field label="Vendor" value={<VendorBadge family={detection.family} vendor={detection.vendor} />} />
                            <Field label="Confidence" value={<ConfidenceBadge confidence={detection.confidence} />} />
                            <Field label="Method" mono value={formatValue(detection.method)} />
                            <Field label="Detected at" mono value={formatTimestamp(detection.detectedAt)} />
                            <Field label="Signals" value={detection.signals.length > 0 ? <ul className="space-y-1 font-mono text-xs font-normal">{detection.signals.map((signal) => <li key={signal}>{signal}</li>)}</ul> : EMPTY_VALUE} />
                            <Field label="Candidates" value={detection.candidates.length > 0 ? <ul className="space-y-1 font-mono text-xs font-normal">{detection.candidates.map((candidate) => <li key={candidate}>{candidate}</li>)}</ul> : EMPTY_VALUE} />
                        </FieldGrid>
                    </Panel>
                ) : null}

                <Panel description="What the recorder reported about itself, and how strongly that attribution is held." eyebrow="Section 01" title="Identity">
                    <FieldGrid>
                        <Field label="Vendor" value={<VendorBadge family={identity.family} vendor={identity.vendor} />} />
                        <Field label="Protocol family" mono value={formatValue(identity.family)} />
                        <Field hint={identity.confidence === "PROBABLE" ? "Fingerprint-derived, not vendor-confirmed." : undefined} label="Confidence" value={<ConfidenceBadge confidence={identity.confidence} />} />
                        <Field label="Recorder kind" mono value={formatValue(identity.kind)} />
                        <Field label="Model" value={formatValue(identity.model)} />
                        <Field label="Serial number" mono value={formatValue(identity.serialNumber)} />
                        <Field label="Firmware" mono value={formatValue(identity.firmwareVersion)} />
                        <Field label="Firmware released" mono value={formatValue(identity.firmwareReleased)} />
                        <Field label="Hardware revision" mono value={formatValue(identity.hardwareVersion)} />
                        <Field label="MAC address" mono value={formatValue(identity.macAddress ?? network.macAddress)} />
                        <Field label="Device name on recorder" value={formatValue(identity.deviceName)} />
                        <Field label="Registered" mono value={formatTimestamp(device.createdAt)} />
                    </FieldGrid>
                </Panel>

                <Panel description="The endpoint this record is bound to, plus the addressing the recorder reports for itself." eyebrow="Section 02" title="Network">
                    <FieldGrid>
                        <Field label="Host" mono value={formatValue(network.host)} />
                        <Field label="HTTP port" mono value={formatValue(network.httpPort)} />
                        <Field label="Transport" mono value={network.useHttps ? "HTTPS" : "HTTP"} />
                        <Field label="HTTPS port" mono value={formatValue(network.httpsPort)} />
                        <Field label="RTSP port" mono value={formatValue(network.rtspPort)} />
                        <Field hint="Vendor private protocol port." label="SDK port" mono value={formatValue(network.sdkPort)} />
                        <Field label="IPv4 address" mono value={formatValue(network.ipv4Address)} />
                        <Field label="Subnet mask" mono value={formatValue(network.subnetMask)} />
                        <Field label="Gateway" mono value={formatValue(network.gateway)} />
                        <Field label="DHCP" value={formatBoolean(network.dhcpEnabled)} />
                    </FieldGrid>
                </Panel>

                <Panel description={`${device.channels.length} channel${device.channels.length === 1 ? "" : "s"} enumerated from the recorder.`} eyebrow="Section 03" title="Channels">
                    {device.channels.length === 0 ? (
                        <p className="p-6 text-sm text-(--secondary-text-color)">No channels have been enumerated. Run Identify with valid credentials to read the channel map.</p>
                    ) : (
                        <TableScroll>
                            <table className="w-full min-w-[48rem] border-collapse text-sm">
                                <caption className="sr-only">Channels enumerated from the recorder</caption>
                                <thead>
                                    <tr>
                                        <th className={TABLE_HEAD} scope="col">Channel</th>
                                        <th className={TABLE_HEAD} scope="col">Name</th>
                                        <th className={TABLE_HEAD} scope="col">Input</th>
                                        <th className={TABLE_HEAD} scope="col">Enabled</th>
                                        <th className={TABLE_HEAD} scope="col">Codec</th>
                                        <th className={TABLE_HEAD} scope="col">Resolution</th>
                                        <th className={TABLE_HEAD} scope="col">Track</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {device.channels.map((channel) => (
                                        <tr key={channel.channelId}>
                                            <th className={`${TABLE_CELL} text-left font-mono text-xs font-semibold`} scope="row">{channel.channelId}</th>
                                            <td className={TABLE_CELL}>{formatValue(channel.name)}</td>
                                            <td className={TABLE_CELL}>{channel.isAnalog === null ? EMPTY_VALUE : channel.isAnalog ? "Analog" : "IP"}</td>
                                            <td className={TABLE_CELL}>{formatBoolean(channel.enabled)}</td>
                                            <td className={`${TABLE_CELL} font-mono text-xs`}>{formatValue(channel.codec)}</td>
                                            <td className={`${TABLE_CELL} font-mono text-xs`}>{formatValue(channel.resolution)}</td>
                                            <td className={`${TABLE_CELL} font-mono text-xs`}>{formatValue(channel.trackId)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </TableScroll>
                    )}
                </Panel>

                <Panel description="Capacity as reported by the recorder. A nearly full volume is a retention question: the oldest footage is the first to be overwritten." eyebrow="Section 04" title="Storage">
                    {device.storage.length === 0 ? (
                        <p className="p-6 text-sm text-(--secondary-text-color)">No storage volumes have been enumerated for this recorder.</p>
                    ) : (
                        <TableScroll>
                            <table className="w-full min-w-[52rem] border-collapse text-sm">
                                <caption className="sr-only">Storage volumes with capacity, used, and free space</caption>
                                <thead>
                                    <tr>
                                        <th className={TABLE_HEAD} scope="col">Volume</th>
                                        <th className={TABLE_HEAD} scope="col">Status</th>
                                        <th className={TABLE_HEAD} scope="col">Capacity</th>
                                        <th className={TABLE_HEAD} scope="col">Used</th>
                                        <th className={TABLE_HEAD} scope="col">Free</th>
                                        <th className={TABLE_HEAD} scope="col">Utilisation</th>
                                        <th className={TABLE_HEAD} scope="col">Property</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {device.storage.map((volume) => {
                                        const ratio = usedRatio(volume);
                                        const percent = ratio === null ? null : Math.round(ratio * 100);
                                        return (
                                            <tr key={volume.storageId}>
                                                <th className={`${TABLE_CELL} text-left font-semibold`} scope="row">{formatValue(volume.name ?? volume.storageId)}<p className="mt-1 font-mono text-[11px] font-normal text-(--muted-text-color)">{volume.kind ? `${volume.kind} · ` : ""}ID {volume.storageId}</p></th>
                                                <td className={`${TABLE_CELL} font-mono text-xs`}>{formatValue(volume.status)}</td>
                                                <td className={`${TABLE_CELL} font-mono text-xs tabular-nums`}>{formatBytes(volume.capacityBytes)}</td>
                                                <td className={`${TABLE_CELL} font-mono text-xs tabular-nums`}>{formatBytes(volume.usedBytes)}</td>
                                                <td className={`${TABLE_CELL} font-mono text-xs tabular-nums`}>{formatBytes(volume.freeBytes)}</td>
                                                <td className={TABLE_CELL}>
                                                    {percent === null ? EMPTY_VALUE : (
                                                        <div className="min-w-40">
                                                            <div aria-label={`${percent}% used`} className="h-2 w-full bg-(--surface-strong-color)" role="img"><div className={`h-full ${percent >= 90 ? "bg-(--danger-color)" : percent >= 75 ? "bg-(--warning-color)" : "bg-(--primary-color)"}`} style={{ width: `${percent}%` }} /></div>
                                                            <p className="mt-1.5 font-mono text-[11px] tabular-nums text-(--secondary-text-color)">{percent}% used · {formatBytes(volume.freeBytes)} free</p>
                                                        </div>
                                                    )}
                                                </td>
                                                <td className={`${TABLE_CELL} font-mono text-xs`}>{formatValue(volume.deviceProperty)}</td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </TableScroll>
                    )}
                </Panel>

                <Panel description={`Recorder clock minus the probing host's clock at probe time. Beyond ±${CLOCK_DRIFT_LIMIT_SECONDS}s every timeline claim needs reconciling before it is used.`} eyebrow="Section 05" title="Clock">
                    <FieldGrid>
                        <Field label="Device time" mono value={formatTimestamp(clock.deviceTime)} />
                        <Field label="Reported verbatim" mono value={formatValue(clock.deviceTimeRaw)} />
                        <Field label="Timezone" mono value={formatValue(clock.timezone)} />
                        <Field hint={driftCritical ? `Beyond the ±${CLOCK_DRIFT_LIMIT_SECONDS}s tolerance. Do not correlate this recorder against another source until the offset is reconciled and recorded.` : undefined} label="Clock drift" mono tone={driftCritical ? "danger" : clock.driftSeconds === null ? "default" : "success"} value={<span className="inline-flex items-center gap-2">{driftCritical ? <TriangleAlert aria-hidden="true" className="size-4" /> : null}{formatDrift(clock.driftSeconds)}</span>} />
                        <Field label="NTP" value={formatBoolean(clock.ntpEnabled)} />
                        <Field label="NTP servers" mono value={clock.ntpServers.length > 0 ? <ul className="space-y-1 text-xs font-normal">{clock.ntpServers.map((server) => <li key={server}>{server}</li>)}</ul> : EMPTY_VALUE} />
                        <Field label="Clock probed at" mono value={formatTimestamp(clock.probedAt)} />
                    </FieldGrid>
                </Panel>

                <Panel description="What the adapter for this recorder can genuinely do. Stages the device cannot support are skipped, never simulated." eyebrow="Section 06" title="Capabilities">
                    <div className="flex flex-wrap gap-2 p-6">
                        {KNOWN_CAPABILITIES.map((capability) => <CapabilityChip available={device.capabilities.includes(capability)} capability={capability} key={capability} />)}
                        {device.capabilities.filter((capability) => !KNOWN_CAPABILITIES.some((known) => known === capability)).map((capability) => <CapabilityChip capability={capability} key={capability} />)}
                    </div>
                    <p className="border-t border-(--border-color) px-6 py-4 text-xs leading-5 text-(--secondary-text-color)">Solid outline · supported by this adapter. Dashed outline · not available on this recorder.</p>
                </Panel>

                {device.latestProbe ? (
                    <Panel description="How the facts above were obtained." eyebrow="Section 07" title="Probe evidence">
                        <FieldGrid>
                            <Field label="Method" mono value={formatValue(device.latestProbe.method)} />
                            <Field label="Started" mono value={formatTimestamp(device.latestProbe.startedAt)} />
                            <Field label="Finished" mono value={formatTimestamp(device.latestProbe.finishedAt)} />
                            <Field label="Duration" mono value={formatDuration(device.latestProbe.durationMs)} />
                            <Field label="Endpoints succeeded" mono value={`${device.latestProbe.endpointsSucceeded.length} of ${device.latestProbe.endpointsAttempted.length || device.latestProbe.endpointsSucceeded.length}`} />
                            <Field label="Artifact SHA-256" mono value={device.latestProbe.sha256 ? <span className="break-all text-xs">{device.latestProbe.sha256}</span> : EMPTY_VALUE} />
                        </FieldGrid>
                        {device.latestProbe.warnings.length > 0 ? <ul className="border-t border-(--border-color) p-6 text-sm text-(--warning-color)">{device.latestProbe.warnings.map((warning) => <li className="flex gap-3" key={warning}><TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />{warning}</li>)}</ul> : null}
                    </Panel>
                ) : null}

                <div className="scroll-mt-24" id="recordings"><RecordingsPanel channels={device.channels} deviceId={deviceId} /></div>

                <div className="scroll-mt-24" id="analysis">
                    <Panel action={<ActionButton Icon={BrainCircuit} disabled={busy} onClick={() => void analyse()} pending={analysing} variant="primary">Run analysis</ActionButton>} description="Consistency checks across the device record: clock drift, retention posture, capability gaps, and anything the probe could not establish." eyebrow="Section 08" title="Analysis findings">
                        {analysis === null ? (
                            <p className="p-6 text-sm text-(--secondary-text-color)">No analysis has been run against this device record yet.</p>
                        ) : (
                            <>
                                <dl className="grid gap-px border-b border-(--border-color) bg-(--border-color) sm:grid-cols-3">
                                    {(["CRITICAL", "WARNING", "INFO"] as const).map((severity) => <div className="bg-(--surface-color) px-6 py-4" key={severity}><dt><SeverityBadge severity={severity} /></dt><dd className="mt-2 text-2xl font-semibold tabular-nums tracking-[-.03em]">{analysis.counts[severity] ?? 0}</dd></div>)}
                                </dl>
                                {analysis.findings.length === 0 ? (
                                    <p className="p-6 text-sm text-(--secondary-text-color)">The analysis returned no findings for this device record.</p>
                                ) : (
                                    <ul className="divide-y divide-(--border-color)">
                                        {analysis.findings.map((finding, index) => (
                                            <li className={`border-l-4 p-6 ${finding.severity === "CRITICAL" ? "border-l-(--danger-color)" : finding.severity === "WARNING" ? "border-l-(--warning-color)" : "border-l-(--primary-color)"}`} key={`${finding.title}-${index}`}>
                                                <div className="flex flex-wrap items-center gap-3">
                                                    <SeverityBadge severity={finding.severity} />
                                                    {finding.category ? <span className={EYEBROW_MUTED}>{finding.category}</span> : null}
                                                </div>
                                                <h3 className="mt-3 text-base font-semibold tracking-[-.01em]">{finding.title}</h3>
                                                {finding.detail ? <p className="mt-2 max-w-3xl text-sm leading-6 text-(--secondary-text-color)">{finding.detail}</p> : null}
                                                {finding.observation ? <p className="mt-3 border-l-2 border-(--border-color) bg-(--surface-muted-color) px-4 py-3 font-mono text-xs leading-5 text-(--secondary-text-color)">{finding.observation}</p> : null}
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </>
                        )}
                    </Panel>
                </div>

                <Panel description="Every action taken against this recorder, in the order it was recorded." eyebrow="Section 09" title="Chain of custody">
                    <CustodyTimeline events={device.custody} />
                </Panel>

                <section className="border border-(--border-color) border-l-4 border-l-(--danger-color) bg-(--surface-color) p-6">
                    <p className={EYEBROW_MUTED}>Irreversible</p>
                    <h2 className="mt-2 text-lg font-semibold tracking-[-.02em]">Remove this device</h2>
                    <p className="mt-2 max-w-2xl text-sm leading-6 text-(--secondary-text-color)">Removing the device drops its record, probe evidence, and custody history from this workspace. Export anything the case depends on first.</p>
                    <div className="mt-5 flex flex-wrap gap-3">
                        {confirmRemoval ? (
                            <>
                                <ActionButton Icon={Trash2} onClick={() => void remove()} pending={removing} variant="danger">Confirm removal</ActionButton>
                                <ActionButton disabled={removing} onClick={() => setConfirmRemoval(false)}>Keep device</ActionButton>
                            </>
                        ) : (
                            <ActionButton Icon={Trash2} disabled={busy} onClick={() => setConfirmRemoval(true)} variant="danger">Remove device</ActionButton>
                        )}
                    </div>
                </section>
            </div>
        </PageShell>
    );
}

"use client";

import { HardDrive, Plus, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useCallback } from "react";
import StatusScreen from "@/components/ui/status-screen";
import { STATE_TONE, StateBadge, VendorBadge } from "@/components/devices/badges";
import { ActionButton, BUTTON, EYEBROW_MUTED, ErrorPanel, LoadingPanel, PageHeader, PageShell, Panel, TABLE_CELL, TABLE_HEAD, TableScroll } from "@/components/devices/ui";
import { listDevices } from "@/lib/devices/api";
import { formatEndpoint, formatRelative, formatTimestamp } from "@/lib/devices/format";
import useResource from "@/lib/devices/use-resource";
import type { Device } from "@/lib/devices/types";

function summarize(devices: Device[]) {
    let verified = 0;
    let inProgress = 0;
    let attention = 0;

    for (const device of devices) {
        const tone = STATE_TONE[device.state];
        if (tone === "success") verified += 1;
        else if (tone === "progress") inProgress += 1;
        else if (tone === "danger") attention += 1;
    }

    return [
        { label: "Registered", value: devices.length },
        { label: "Established", value: verified },
        { label: "In progress", value: inProgress },
        { label: "Need attention", value: attention },
    ];
}

export default function DeviceList() {
    const load = useCallback(() => listDevices(), []);
    const { data, error, loading, reload } = useResource(load);
    const devices = data ?? [];

    return (
        <PageShell>
            <PageHeader
                actions={<><ActionButton Icon={RotateCcw} onClick={() => void reload()} pending={loading && data !== null}>Refresh</ActionButton><Link className={BUTTON.primary} href="/dashboard/devices/new"><Plus aria-hidden="true" className="size-4" />Add device</Link></>}
                description="Recorders registered to this workspace. Vendor and model attribution is only as strong as the probe that produced it — check the confidence on each device before citing it."
                eyebrow="Evidence sources"
                title="Devices"
            />

            <div className="mt-8">
                {loading && data === null ? <LoadingPanel label="Loading registered devices" /> : null}
                {!loading && error ? <ErrorPanel message={error} onRetry={() => void reload()} title="Device list unavailable" /> : null}

                {!error && data !== null && devices.length === 0 ? (
                    <StatusScreen
                        action={<Link className={BUTTON.primary} href="/dashboard/devices/new"><Plus aria-hidden="true" className="size-4" />Add device</Link>}
                        description="No recorder has been registered in this workspace yet. Register one to capture its identity, channels, storage, and clock state before any acquisition begins."
                        embedded
                        eyebrow="Nothing registered"
                        icon={<HardDrive aria-hidden="true" className="size-5" />}
                        title="No devices on record"
                    />
                ) : null}

                {!error && devices.length > 0 ? (
                    <div className="space-y-8">
                        <dl className="grid gap-px border border-(--border-color) bg-(--border-color) sm:grid-cols-4">
                            {summarize(devices).map((item) => <div className="bg-(--surface-color) px-5 py-4" key={item.label}><dt className={EYEBROW_MUTED}>{item.label}</dt><dd className="mt-2 text-2xl font-semibold tracking-[-.03em]">{item.value}</dd></div>)}
                        </dl>

                        <Panel description="Every row links to the full device record, including its probe evidence and custody history." eyebrow="Registry" title={`${devices.length} recorder${devices.length === 1 ? "" : "s"}`}>
                            <TableScroll>
                                <table className="w-full min-w-[56rem] border-collapse text-sm">
                                    <caption className="sr-only">Registered recorders with endpoint, vendor attribution, lifecycle state, channel count, and last probe time</caption>
                                    <thead>
                                        <tr>
                                            <th className={TABLE_HEAD} scope="col">Device</th>
                                            <th className={TABLE_HEAD} scope="col">Endpoint</th>
                                            <th className={TABLE_HEAD} scope="col">Vendor</th>
                                            <th className={TABLE_HEAD} scope="col">State</th>
                                            <th className={TABLE_HEAD} scope="col">Channels</th>
                                            <th className={TABLE_HEAD} scope="col">Last probed</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {devices.map((device) => (
                                            <tr className="transition-colors hover:bg-(--surface-muted-color)" key={device.id || device.name}>
                                                <th className={`${TABLE_CELL} text-left font-semibold`} scope="row"><Link className="text-(--primary-color) hover:text-(--secondary-color)" href={`/dashboard/devices/${encodeURIComponent(device.id)}`}>{device.name}</Link>{device.identity.model ? <p className="mt-1 text-xs font-normal text-(--secondary-text-color)">{device.identity.model}</p> : null}</th>
                                                <td className={`${TABLE_CELL} font-mono text-xs text-(--secondary-text-color)`}>{formatEndpoint(device)}</td>
                                                <td className={TABLE_CELL}><VendorBadge family={device.identity.family} vendor={device.identity.vendor} /></td>
                                                <td className={TABLE_CELL}><StateBadge state={device.state} /></td>
                                                <td className={`${TABLE_CELL} font-mono tabular-nums`}>{device.channelCount}</td>
                                                <td className={TABLE_CELL}><span className="whitespace-nowrap">{formatRelative(device.lastProbedAt)}</span><p className="mt-1 font-mono text-[11px] text-(--muted-text-color)">{formatTimestamp(device.lastProbedAt)}</p></td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </TableScroll>
                        </Panel>
                    </div>
                ) : null}
            </div>
        </PageShell>
    );
}

"use client";

import { ArrowRight, FileClock, HardDrive, Plus, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useCallback } from "react";
import { STATE_NOTE, STATE_TONE, StateBadge } from "@/components/devices/badges";
import { ActionButton, BUTTON, EYEBROW_MUTED, ErrorPanel, LoadingPanel, PageHeader, PageShell, Panel } from "@/components/devices/ui";
import StatusScreen from "@/components/ui/status-screen";
import { listCustody, listDevices } from "@/lib/devices/api";
import { formatRelative, formatTimestamp } from "@/lib/devices/format";
import useResource from "@/lib/devices/use-resource";
import { DEVICE_STATES, type CustodyEvent, type Device, type DeviceState } from "@/lib/devices/types";

type WorkspaceSnapshot = {
    devices: Device[];
    events: { event: CustodyEvent; device: Device }[];
};

const CUSTODY_DEVICE_LIMIT = 5;
const CUSTODY_EVENT_LIMIT = 8;

async function loadWorkspace(): Promise<WorkspaceSnapshot> {
    const devices = await listDevices();
    const recent = [...devices]
        .sort((a, b) => (b.lastProbedAt ?? b.updatedAt ?? "").localeCompare(a.lastProbedAt ?? a.updatedAt ?? ""))
        .slice(0, CUSTODY_DEVICE_LIMIT);

    const collected = await Promise.all(recent.map(async (device) => {
        if (!device.id) return [];
        try {
            const events = await listCustody(device.id, { silent: true });
            return events.map((event) => ({ event, device }));
        } catch {
            // A device whose custody log cannot be read must not blank the overview.
            return [];
        }
    }));

    const events = collected
        .flat()
        .sort((a, b) => (b.event.recordedAt ?? "").localeCompare(a.event.recordedAt ?? ""))
        .slice(0, CUSTODY_EVENT_LIMIT);

    return { devices, events };
}

export default function DashboardOverview() {
    const load = useCallback(() => loadWorkspace(), []);
    const { data, error, loading, reload } = useResource(load);
    const devices = data?.devices ?? [];
    const events = data?.events ?? [];

    const byState = new Map<DeviceState, number>();
    for (const device of devices) byState.set(device.state, (byState.get(device.state) ?? 0) + 1);
    const breakdown = DEVICE_STATES.filter((state) => byState.has(state)).map((state) => ({ state, count: byState.get(state) ?? 0 }));
    const peak = breakdown.reduce((highest, entry) => Math.max(highest, entry.count), 0);

    const tallies = [
        { label: "Registered", value: devices.length, hint: "Recorders in this workspace" },
        { label: "Established", value: devices.filter((device) => STATE_TONE[device.state] === "success").length, hint: "Last stage completed cleanly" },
        { label: "In progress", value: devices.filter((device) => STATE_TONE[device.state] === "progress").length, hint: "A stage is running" },
        { label: "Need attention", value: devices.filter((device) => STATE_TONE[device.state] === "danger").length, hint: "Unreachable, rejected, or failed" },
    ];

    return (
        <PageShell>
            <PageHeader
                actions={<><ActionButton Icon={RotateCcw} onClick={() => void reload()} pending={loading && data !== null}>Refresh</ActionButton><Link className={BUTTON.primary} href="/dashboard/devices/new"><Plus aria-hidden="true" className="size-4" />Add device</Link></>}
                description="The state of every recorder registered to this workspace, and the most recent actions recorded against them."
                eyebrow="Case workspace"
                title="Overview"
            />

            <div className="mt-8">
                {loading && data === null ? <LoadingPanel label="Loading workspace overview" /> : null}
                {!loading && error ? <ErrorPanel message={error} onRetry={() => void reload()} title="Workspace overview unavailable" /> : null}

                {!error && data !== null && devices.length === 0 ? (
                    <StatusScreen
                        action={<Link className={BUTTON.primary} href="/dashboard/devices/new"><Plus aria-hidden="true" className="size-4" />Add device</Link>}
                        description="This workspace has no recorders yet. Register the first one to capture its identity, channels, storage, and clock state under a custody record."
                        embedded
                        eyebrow="Nothing to review"
                        icon={<HardDrive aria-hidden="true" className="size-5" />}
                        title="The workspace is empty"
                    />
                ) : null}

                {!error && devices.length > 0 ? (
                    <div className="space-y-8">
                        <dl className="grid gap-px border border-(--border-color) bg-(--border-color) sm:grid-cols-2 lg:grid-cols-4">
                            {tallies.map((item) => <div className="bg-(--surface-color) px-6 py-5" key={item.label}><dt className={EYEBROW_MUTED}>{item.label}</dt><dd className="mt-2 text-3xl font-semibold tracking-[-.04em]">{item.value}</dd><p className="mt-2 text-xs leading-5 text-(--secondary-text-color)">{item.hint}</p></div>)}
                        </dl>

                        <div className="grid gap-8 lg:grid-cols-2">
                            <Panel description="Where each registered recorder currently sits in the workflow." eyebrow="Lifecycle" title="Devices by state">
                                <ul className="divide-y divide-(--border-color)">
                                    {breakdown.map(({ state, count }) => (
                                        <li className="px-6 py-4" key={state}>
                                            <div className="flex flex-wrap items-center justify-between gap-3">
                                                <StateBadge state={state} />
                                                <span className="font-mono text-sm font-semibold tabular-nums">{count}</span>
                                            </div>
                                            <div aria-hidden="true" className="mt-3 h-1.5 w-full bg-(--surface-muted-color)"><div className={`h-full ${STATE_TONE[state] === "danger" ? "bg-(--danger-color)" : STATE_TONE[state] === "progress" ? "bg-(--warning-color)" : STATE_TONE[state] === "success" ? "bg-(--success-color)" : "bg-(--muted-text-color)"}`} style={{ width: `${peak > 0 ? Math.round((count / peak) * 100) : 0}%` }} /></div>
                                            <p className="mt-2 text-xs leading-5 text-(--secondary-text-color)">{STATE_NOTE[state]}</p>
                                        </li>
                                    ))}
                                </ul>
                            </Panel>

                            <Panel action={<Link className={BUTTON.secondary} href="/dashboard/devices">All devices<ArrowRight aria-hidden="true" className="size-4" /></Link>} description={`The latest recorded actions across the ${Math.min(devices.length, CUSTODY_DEVICE_LIMIT)} most recently probed recorders.`} eyebrow="Chain of custody" title="Recent custody events">
                                {events.length === 0 ? (
                                    <p className="flex items-center gap-3 p-6 text-sm text-(--secondary-text-color)"><FileClock aria-hidden="true" className="size-4 text-(--muted-text-color)" />No custody events have been recorded yet. They appear here as soon as a device is probed or acquired.</p>
                                ) : (
                                    <ol className="divide-y divide-(--border-color)">
                                        {events.map(({ event, device }) => (
                                            <li className="px-6 py-4" key={`${device.id}-${event.id}`}>
                                                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                                                    <p className="font-mono text-xs font-semibold uppercase tracking-[.16em]">{event.action.replace(/_/g, " ")}</p>
                                                    <p className={EYEBROW_MUTED} title={formatTimestamp(event.recordedAt)}>{formatRelative(event.recordedAt)}</p>
                                                </div>
                                                <p className="mt-2 text-sm text-(--secondary-text-color)">{event.detail ?? "No detail recorded."}</p>
                                                <p className="mt-2 text-xs"><Link className="font-semibold text-(--primary-color) hover:text-(--secondary-color)" href={`/dashboard/devices/${encodeURIComponent(device.id)}`}>{device.name}</Link>{event.actor ? <span className="text-(--secondary-text-color)"> · {event.actor}</span> : null}</p>
                                            </li>
                                        ))}
                                    </ol>
                                )}
                            </Panel>
                        </div>

                        <Panel description="The parts of the workflow that are wired up today." eyebrow="Quick links" title="Where to go next">
                            <div className="grid gap-px bg-(--border-color) sm:grid-cols-2">
                                <Link className="group bg-(--surface-color) px-6 py-5 transition-colors hover:bg-(--surface-muted-color)" href="/dashboard/devices"><p className={EYEBROW_MUTED}>Registry</p><p className="mt-2 flex items-center gap-2 text-sm font-semibold">Device registry<ArrowRight aria-hidden="true" className="size-4 text-(--primary-color)" /></p><p className="mt-2 text-xs leading-5 text-(--secondary-text-color)">Every registered recorder, its attribution, and its lifecycle state.</p></Link>
                                <Link className="group bg-(--surface-color) px-6 py-5 transition-colors hover:bg-(--surface-muted-color)" href="/dashboard/devices/new"><p className={EYEBROW_MUTED}>Intake</p><p className="mt-2 flex items-center gap-2 text-sm font-semibold">Register a device<ArrowRight aria-hidden="true" className="size-4 text-(--primary-color)" /></p><p className="mt-2 text-xs leading-5 text-(--secondary-text-color)">Add a recorder and open its custody record with the first probe.</p></Link>
                            </div>
                        </Panel>
                    </div>
                ) : null}
            </div>
        </PageShell>
    );
}

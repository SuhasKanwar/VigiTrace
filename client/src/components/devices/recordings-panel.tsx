"use client";

import { Download, FileSearch, History, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { ActionButton, EYEBROW_MUTED, Panel, TABLE_CELL, TABLE_HEAD, TableScroll } from "@/components/devices/ui";
import { createAcquisition, listRecordings, readErrorMessage, searchRecordings } from "@/lib/devices/api";
import { EMPTY_VALUE, formatBytes, formatTimestamp, fromLocalInputValue, toLocalInputValue } from "@/lib/devices/format";
import type { DeviceChannel, Recording, RecordingIndex } from "@/lib/devices/types";

const DAY_MS = 86_400_000;

function spanDuration(start: string | null, end: string | null): string {
    if (!start || !end) return EMPTY_VALUE;
    const milliseconds = new Date(end).getTime() - new Date(start).getTime();
    if (!Number.isFinite(milliseconds) || milliseconds < 0) return EMPTY_VALUE;

    const seconds = Math.round(milliseconds / 1000);
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);

    if (hours > 0) return `${hours}h ${String(minutes).padStart(2, "0")}m`;
    if (minutes > 0) return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
    return `${seconds}s`;
}

export default function RecordingsPanel({ deviceId, channels }: { deviceId: string; channels: DeviceChannel[] }) {
    const [start, setStart] = useState(() => toLocalInputValue(new Date(Date.now() - DAY_MS)));
    const [end, setEnd] = useState(() => toLocalInputValue(new Date()));
    const [maxResults, setMaxResults] = useState("200");
    const [selected, setSelected] = useState<string[]>([]);
    const [index, setIndex] = useState<RecordingIndex | null>(null);
    const [pending, setPending] = useState(false);
    const [loadingStored, setLoadingStored] = useState(false);
    const [acquiring, setAcquiring] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [rangeError, setRangeError] = useState<string | null>(null);

    function toggleChannel(channelId: string) {
        setSelected((current) => (current.includes(channelId) ? current.filter((entry) => entry !== channelId) : [...current, channelId]));
    }

    async function search() {
        const startIso = fromLocalInputValue(start);
        const endIso = fromLocalInputValue(end);

        if (!startIso || !endIso) {
            setRangeError("Enter both a start and an end for the search window.");
            return;
        }

        if (new Date(startIso).getTime() >= new Date(endIso).getTime()) {
            setRangeError("The start of the window must fall before its end.");
            return;
        }

        setRangeError(null);
        setError(null);
        setPending(true);

        try {
            setIndex(await searchRecordings(deviceId, {
                channelIds: selected.length > 0 ? selected : channels.map((channel) => channel.channelId),
                start: startIso,
                end: endIso,
                maxResults: Math.min(Math.max(Number(maxResults) || 200, 1), 5000),
            }));
        } catch (cause) {
            setIndex(null);
            setError(readErrorMessage(cause));
        } finally {
            setPending(false);
        }
    }

    async function loadStored() {
        setError(null);
        setLoadingStored(true);

        try {
            setIndex(await listRecordings(deviceId));
        } catch (cause) {
            setError(readErrorMessage(cause, "No stored recording index is available for this device yet."));
        } finally {
            setLoadingStored(false);
        }
    }

    async function acquire(recording: Recording) {
        if (!recording.start || !recording.end) return;
        setAcquiring(recording.recordingId);

        try {
            await createAcquisition(deviceId, {
                recordingId: recording.recordingId,
                channelId: recording.channelId,
                start: recording.start,
                end: recording.end,
                playbackUri: recording.playbackUri ?? undefined,
                filePath: recording.filePath ?? undefined,
            });
        } catch {
            // Reported by the response interceptor; the index stays as it was.
        } finally {
            setAcquiring(null);
        }
    }

    const recordings = index?.recordings ?? [];

    return (
        <Panel
            action={<><ActionButton Icon={History} onClick={() => void loadStored()} pending={loadingStored}>Stored index</ActionButton><ActionButton Icon={FileSearch} onClick={() => void search()} pending={pending} variant="primary">Search recordings</ActionButton></>}
            description="Reads the recorder's own recording index for the window below. Gaps between segments are where unindexed or deleted footage would sit."
            eyebrow="Recording index"
            title="Recordings"
        >
            <div className="border-b border-(--border-color) p-6">
                <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
                    <div><label className="block text-sm font-semibold" htmlFor="recording-start">Window start</label><input aria-describedby={rangeError ? "recording-range-error" : undefined} aria-invalid={rangeError ? true : undefined} className={`mt-2 w-full border bg-(--primary-bg-color) px-4 py-3 font-mono text-xs outline-none transition-colors focus:border-(--primary-color) ${rangeError ? "border-(--danger-color)" : "border-(--border-color)"}`} id="recording-start" onChange={(event) => setStart(event.target.value)} type="datetime-local" value={start} /></div>
                    <div><label className="block text-sm font-semibold" htmlFor="recording-end">Window end</label><input aria-describedby={rangeError ? "recording-range-error" : undefined} aria-invalid={rangeError ? true : undefined} className={`mt-2 w-full border bg-(--primary-bg-color) px-4 py-3 font-mono text-xs outline-none transition-colors focus:border-(--primary-color) ${rangeError ? "border-(--danger-color)" : "border-(--border-color)"}`} id="recording-end" onChange={(event) => setEnd(event.target.value)} type="datetime-local" value={end} /></div>
                    <div><label className="block text-sm font-semibold" htmlFor="recording-max">Max results</label><input className="mt-2 w-full border border-(--border-color) bg-(--primary-bg-color) px-4 py-3 font-mono text-xs outline-none transition-colors focus:border-(--primary-color)" id="recording-max" inputMode="numeric" onChange={(event) => setMaxResults(event.target.value)} value={maxResults} /></div>
                    <div><p className={EYEBROW_MUTED}>Window is local time</p><p className="mt-2 text-xs leading-5 text-(--secondary-text-color)">Sent to the recorder as UTC. Results are shown in UTC and are not corrected for clock drift.</p></div>
                </div>

                {rangeError ? <p className="mt-4 border-l-2 border-(--danger-color) pl-3 text-xs font-semibold leading-5 text-(--danger-color)" id="recording-range-error">{rangeError}</p> : null}

                <fieldset className="mt-6 border-t border-(--border-color) pt-5">
                    <legend className="sr-only">Channels to search</legend>
                    <p className={EYEBROW_MUTED}>Channels {selected.length === 0 ? "· all channels" : `· ${selected.length} selected`}</p>
                    {channels.length === 0 ? (
                        <p className="mt-3 text-sm text-(--secondary-text-color)">No channels have been enumerated yet. Run Identify first.</p>
                    ) : (
                        <div className="mt-3 flex flex-wrap gap-2">
                            {channels.map((channel) => {
                                const active = selected.includes(channel.channelId);
                                return <label className={`inline-flex cursor-pointer items-center gap-2 border px-3 py-2 font-mono text-[11px] uppercase tracking-[.12em] transition-colors ${active ? "border-(--primary-color) bg-(--surface-strong-color) text-(--primary-text-color)" : "border-(--border-color) bg-(--surface-color) text-(--secondary-text-color) hover:bg-(--surface-muted-color)"}`} key={channel.channelId}><input checked={active} className="size-3.5 accent-(--primary-color)" onChange={() => toggleChannel(channel.channelId)} type="checkbox" />CH {channel.channelId}{channel.name ? <span className="normal-case tracking-normal text-(--muted-text-color)">{channel.name}</span> : null}</label>;
                            })}
                        </div>
                    )}
                </fieldset>
            </div>

            {error ? <p className="flex gap-3 border-b border-(--border-color) bg-(--surface-muted-color) p-6 text-sm text-(--danger-color)"><TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />{error}</p> : null}

            {index && index.warnings.length > 0 ? (
                <ul className="border-b border-(--border-color) bg-(--surface-muted-color) p-6 text-sm text-(--warning-color)">{index.warnings.map((warning) => <li className="flex gap-3" key={warning}><TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />{warning}</li>)}</ul>
            ) : null}

            {index && index.truncated ? <p className="border-b border-(--border-color) border-l-4 border-l-(--warning-color) bg-(--surface-muted-color) p-6 text-sm font-semibold text-(--warning-color)">The recorder capped this result set. More segments exist inside the window than are listed below — narrow the window before drawing any conclusion about coverage.</p> : null}

            {index === null ? (
                <p className="p-6 text-sm text-(--secondary-text-color)">No search has been run. Choose a window and search the recorder&apos;s index, or load the index already stored for this device.</p>
            ) : recordings.length === 0 ? (
                <p className="p-6 text-sm text-(--secondary-text-color)">The recorder reported no segments in this window. That is itself a finding — record the window you searched.</p>
            ) : (
                <TableScroll>
                    <table className="w-full min-w-[64rem] border-collapse text-sm">
                        <caption className="sr-only">Recording segments returned by the recorder index</caption>
                        <thead>
                            <tr>
                                <th className={TABLE_HEAD} scope="col">Recording</th>
                                <th className={TABLE_HEAD} scope="col">Channel</th>
                                <th className={TABLE_HEAD} scope="col">Start (UTC)</th>
                                <th className={TABLE_HEAD} scope="col">End (UTC)</th>
                                <th className={TABLE_HEAD} scope="col">Duration</th>
                                <th className={TABLE_HEAD} scope="col">Size</th>
                                <th className={TABLE_HEAD} scope="col">Trigger</th>
                                <th className={TABLE_HEAD} scope="col"><span className="sr-only">Acquire</span></th>
                            </tr>
                        </thead>
                        <tbody>
                            {recordings.map((recording) => (
                                <tr className="transition-colors hover:bg-(--surface-muted-color)" key={`${recording.channelId}-${recording.recordingId}`}>
                                    <th className={`${TABLE_CELL} text-left font-mono text-xs font-semibold`} scope="row">{recording.recordingId}{recording.eventType ? <p className="mt-1 font-sans text-xs font-normal text-(--secondary-text-color)">{recording.eventType}</p> : null}</th>
                                    <td className={`${TABLE_CELL} font-mono text-xs`}>{recording.channelId}</td>
                                    <td className={`${TABLE_CELL} font-mono text-xs whitespace-nowrap`}>{formatTimestamp(recording.start)}</td>
                                    <td className={`${TABLE_CELL} font-mono text-xs whitespace-nowrap`}>{formatTimestamp(recording.end)}</td>
                                    <td className={`${TABLE_CELL} font-mono text-xs tabular-nums`}>{spanDuration(recording.start, recording.end)}</td>
                                    <td className={`${TABLE_CELL} font-mono text-xs tabular-nums`}>{formatBytes(recording.sizeBytes)}</td>
                                    <td className={`${TABLE_CELL} text-xs`}>{recording.recordTrigger ?? EMPTY_VALUE}{typeof recording.overwriteCount === "number" ? <p className="mt-1 text-xs text-(--warning-color)">Overwritten ×{recording.overwriteCount}</p> : null}</td>
                                    <td className={`${TABLE_CELL} text-right`}><ActionButton Icon={Download} disabled={!recording.start || !recording.end} onClick={() => void acquire(recording)} pending={acquiring === recording.recordingId} title="Queue a controlled export of this segment">Acquire</ActionButton></td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </TableScroll>
            )}
        </Panel>
    );
}

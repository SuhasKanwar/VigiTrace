"use client";

import { ArrowLeft, ShieldAlert, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useCallback, useMemo, useState } from "react";
import { CapabilityChip } from "@/components/devices/badges";
import { ActionButton, BUTTON, EYEBROW_MUTED, PageHeader, PageShell, Panel } from "@/components/devices/ui";
import { createDevice, listVendors } from "@/lib/devices/api";
import useResource from "@/lib/devices/use-resource";
import { VENDOR_HINTS, type CreateDeviceInput, type VendorHint } from "@/lib/devices/types";

type FormValues = {
    name: string;
    host: string;
    httpPort: string;
    useHttps: boolean;
    username: string;
    password: string;
    vendorHint: string;
};

type FieldName = keyof Omit<FormValues, "useHttps">;

const INITIAL: FormValues = { name: "", host: "", httpPort: "80", useHttps: false, username: "", password: "", vendorHint: "" };

/** Hostname or IPv4 literal. Anything with a scheme, path, or port belongs in another field. */
const HOST_PATTERN = /^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$/;

function validate(values: FormValues): Partial<Record<FieldName, string>> {
    const errors: Partial<Record<FieldName, string>> = {};
    const host = values.host.trim();
    const port = Number(values.httpPort);

    if (!values.name.trim()) errors.name = "Give the recorder a name that will identify it in the case record.";
    else if (values.name.trim().length > 120) errors.name = "Keep the name under 120 characters.";

    if (!host) errors.host = "Enter the recorder's IP address or hostname.";
    else if (/^[a-z]+:\/\//i.test(host)) errors.host = "Enter the host only — no http:// or https:// prefix. Use the HTTPS switch below.";
    else if (host.includes(":") || host.includes("/")) errors.host = "Enter the host only — the port goes in its own field.";
    else if (!HOST_PATTERN.test(host)) errors.host = "This is not a valid IP address or hostname.";

    if (!values.httpPort.trim()) errors.httpPort = "Enter the HTTP port the recorder answers on.";
    else if (!Number.isInteger(port) || port < 1 || port > 65535) errors.httpPort = "The port must be a whole number between 1 and 65535.";

    if (!values.username.trim()) errors.username = "Credentials are required — an unauthenticated probe cannot confirm a vendor.";
    if (!values.password) errors.password = "Enter the password for this account on the recorder.";

    return errors;
}

export default function DeviceForm() {
    const router = useRouter();
    const [values, setValues] = useState<FormValues>(INITIAL);
    const [errors, setErrors] = useState<Partial<Record<FieldName, string>>>({});
    const [submitted, setSubmitted] = useState(false);
    const [pending, setPending] = useState(false);

    const loadVendors = useCallback(() => listVendors(), []);
    const { data: adapters } = useResource(loadVendors);

    const vendorOptions = useMemo(() => {
        const reported = (adapters ?? []).map((adapter) => adapter.vendor).filter((vendor) => vendor && vendor !== "UNKNOWN");
        return reported.length > 0 ? Array.from(new Set(reported)) : [...VENDOR_HINTS];
    }, [adapters]);

    const selectedAdapter = useMemo(() => (adapters ?? []).find((adapter) => adapter.vendor === values.vendorHint) ?? null, [adapters, values.vendorHint]);

    function update<K extends keyof FormValues>(field: K, value: FormValues[K]) {
        const next: FormValues = { ...values, [field]: value };

        if (field === "useHttps") {
            if (value === true && values.httpPort === "80") next.httpPort = "443";
            if (value === false && values.httpPort === "443") next.httpPort = "80";
        }

        setValues(next);
        if (submitted) setErrors(validate(next));
    }

    async function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        setSubmitted(true);

        const found = validate(values);
        setErrors(found);
        if (Object.keys(found).length > 0) {
            document.getElementById(`device-${Object.keys(found)[0]}`)?.focus();
            return;
        }

        const payload: CreateDeviceInput = {
            name: values.name.trim(),
            host: values.host.trim(),
            httpPort: Number(values.httpPort),
            useHttps: values.useHttps,
            username: values.username.trim(),
            password: values.password,
        };

        if (values.vendorHint) payload.vendorHint = values.vendorHint as VendorHint;

        setPending(true);

        try {
            const device = await createDevice(payload);
            router.push(device.id ? `/dashboard/devices/${encodeURIComponent(device.id)}` : "/dashboard/devices");
            router.refresh();
        } catch {
            // The response interceptor has already reported the failure; keep the form intact.
            setPending(false);
        }
    }

    return (
        <PageShell>
            <PageHeader
                actions={<Link className={BUTTON.secondary} href="/dashboard/devices"><ArrowLeft aria-hidden="true" className="size-4" />Back to devices</Link>}
                description="Register a recorder so VigiTrace can fingerprint it, read its channels, storage, and clock, and hold the result under one custody record."
                eyebrow="New evidence source"
                title="Add device"
            />

            <form className="mt-8 grid gap-8 lg:grid-cols-[1.4fr_1fr] lg:items-start" noValidate onSubmit={submit}>
                <div className="space-y-8">
                    <Panel description="How the recorder is reached on the network." eyebrow="Step 01" title="Endpoint">
                        <div className="space-y-6 p-6">
                            <TextField autoComplete="off" error={errors.name} hint="Used on every report and custody entry for this recorder." label="Device name" name="name" onChange={(value) => update("name", value)} placeholder="Riverside precinct · rear entrance NVR" value={values.name} />
                            <div className="grid gap-6 sm:grid-cols-[2fr_1fr]">
                                <TextField autoComplete="off" error={errors.host} inputMode="url" label="Host" name="host" onChange={(value) => update("host", value)} placeholder="192.168.1.108" value={values.host} />
                                <TextField autoComplete="off" error={errors.httpPort} inputMode="numeric" label="HTTP port" name="httpPort" onChange={(value) => update("httpPort", value)} placeholder="80" value={values.httpPort} />
                            </div>
                            <label className="flex items-start gap-3 border border-(--border-color) bg-(--primary-bg-color) p-4 text-sm font-semibold">
                                <input checked={values.useHttps} className="mt-0.5 size-4 shrink-0 accent-(--primary-color)" name="useHttps" onChange={(event) => update("useHttps", event.target.checked)} type="checkbox" />
                                <span>Use HTTPS<span className="mt-1 block text-xs font-normal leading-5 text-(--secondary-text-color)">Most recorders ship with a self-signed certificate. Certificate validation is not treated as an identity signal.</span></span>
                            </label>
                        </div>
                    </Panel>

                    <Panel description="Probes run authenticated. Without valid credentials a vendor can only be guessed from its fingerprint, never confirmed." eyebrow="Step 02" title="Credentials">
                        <div className="space-y-6 p-6">
                            <TextField autoComplete="off" error={errors.username} label="Username" name="username" onChange={(value) => update("username", value)} placeholder="admin" value={values.username} />
                            <TextField autoComplete="new-password" error={errors.password} label="Password" name="password" onChange={(value) => update("password", value)} type="password" value={values.password} />
                            <p className="flex gap-3 border-l-2 border-(--warning-color) bg-(--surface-muted-color) px-4 py-3 text-xs leading-5 text-(--warning-color)"><ShieldAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />Repeated failed sign-ins can lock the account on some recorders. Confirm the credentials before registering.</p>
                        </div>
                    </Panel>

                    <Panel description="Optional. Detection still runs and may disagree with the hint — the recorder's own response decides." eyebrow="Step 03" title="Vendor hint">
                        <div className="space-y-4 p-6">
                            <label className="block text-sm font-semibold" htmlFor="device-vendorHint">Vendor
                                <select className="mt-2 w-full border border-(--border-color) bg-(--primary-bg-color) px-4 py-3 font-normal outline-none transition-colors focus:border-(--primary-color)" id="device-vendorHint" name="vendorHint" onChange={(event) => update("vendorHint", event.target.value)} value={values.vendorHint}>
                                    <option value="">Auto-detect (recommended)</option>
                                    {vendorOptions.map((vendor) => <option key={vendor} value={vendor}>{vendor}</option>)}
                                </select>
                            </label>
                            {selectedAdapter ? (
                                <div className="border border-(--border-color) bg-(--primary-bg-color) p-4">
                                    <p className={EYEBROW_MUTED}>{selectedAdapter.family ? `${selectedAdapter.family} protocol family` : "Adapter"}</p>
                                    <div className="mt-3 flex flex-wrap gap-2">{selectedAdapter.capabilities.map((capability) => <CapabilityChip capability={capability} key={capability} />)}</div>
                                    {selectedAdapter.provenance ? <p className="mt-3 text-xs leading-5 text-(--secondary-text-color)">{selectedAdapter.provenance}</p> : null}
                                </div>
                            ) : null}
                        </div>
                    </Panel>
                </div>

                <aside className="border border-(--border-color) border-l-4 border-l-(--primary-color) bg-(--surface-color) p-6 lg:sticky lg:top-24">
                    <p className={EYEBROW_MUTED}>Before you register</p>
                    <h2 className="mt-2 text-lg font-semibold tracking-[-.02em]">Registration is the first custody event</h2>
                    <p className="mt-3 text-sm leading-6 text-(--secondary-text-color)">Adding a recorder records who added it and when. Nothing is read from the device until you run Detect or Identify on its record.</p>
                    <ul className="mt-5 space-y-3 border-t border-(--border-color) pt-5 text-sm text-(--secondary-text-color)">
                        <li className="flex gap-3"><span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-(--primary-color)" />Detect fingerprints the recorder without authenticating.</li>
                        <li className="flex gap-3"><span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-(--primary-color)" />Identify authenticates and reads channels, storage, and clock.</li>
                        <li className="flex gap-3"><span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-(--primary-color)" />Only an authenticated probe can raise attribution to confirmed.</li>
                    </ul>
                    <div className="mt-7 flex flex-wrap gap-3 border-t border-(--border-color) pt-6">
                        <ActionButton Icon={Plus} pending={pending} type="submit" variant="primary">Register device</ActionButton>
                        <Link className={BUTTON.secondary} href="/dashboard/devices">Cancel</Link>
                    </div>
                </aside>
            </form>
        </PageShell>
    );
}

function TextField({ label, name, value, onChange, error, hint, type = "text", placeholder, autoComplete, inputMode }: { label: string; name: FieldName; value: string; onChange: (value: string) => void; error?: string; hint?: string; type?: "text" | "password"; placeholder?: string; autoComplete?: string; inputMode?: "url" | "numeric" }) {
    const id = `device-${name}`;
    const describedBy = [error ? `${id}-error` : null, hint ? `${id}-hint` : null].filter(Boolean).join(" ") || undefined;

    return (
        <div>
            <label className="block text-sm font-semibold" htmlFor={id}>{label}</label>
            <input aria-describedby={describedBy} aria-invalid={error ? true : undefined} autoComplete={autoComplete} className={`mt-2 w-full border bg-(--primary-bg-color) px-4 py-3 font-normal outline-none transition-colors focus:border-(--primary-color) ${error ? "border-(--danger-color)" : "border-(--border-color)"}`} id={id} inputMode={inputMode} name={name} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} type={type} value={value} />
            {hint && !error ? <p className="mt-2 text-xs leading-5 text-(--secondary-text-color)" id={`${id}-hint`}>{hint}</p> : null}
            {error ? <p className="mt-2 border-l-2 border-(--danger-color) pl-3 text-xs leading-5 font-semibold text-(--danger-color)" id={`${id}-error`}>{error}</p> : null}
        </div>
    );
}

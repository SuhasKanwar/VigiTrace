import type { AxiosResponse } from "axios";
import api from "@/lib/api";
import {
    asRecord,
    normalizeAnalysis,
    normalizeCustodyEvent,
    normalizeDetection,
    normalizeDevice,
    normalizeRecordingIndex,
    normalizeVendorAdapter,
} from "./normalize";
import type {
    AcquisitionInput,
    AnalysisReport,
    CreateDeviceInput,
    CustodyEvent,
    DetectionResult,
    Device,
    RecordingIndex,
    RecordingSearchInput,
    VendorAdapter,
} from "./types";

/** Every server response is `{ success, message, data?, error? }`; the payload is under `data`. */
function payloadOf(response: AxiosResponse): Record<string, unknown> {
    return asRecord(asRecord(response.data).data);
}

function listOf(payload: Record<string, unknown>, key: string): unknown[] {
    const value = payload[key];
    return Array.isArray(value) ? value : [];
}

export function readErrorMessage(error: unknown, fallback = "The request could not be completed."): string {
    if (typeof error === "object" && error !== null) {
        const response = asRecord(asRecord(error).response);
        const message = asRecord(response.data).message ?? asRecord(error).message;
        if (typeof message === "string" && message.trim()) return message.trim();
    }
    return fallback;
}

export async function listVendors(): Promise<VendorAdapter[]> {
    const response = await api.get("/api/devices/vendors", { silentToast: true });
    return listOf(payloadOf(response), "vendors").map(normalizeVendorAdapter);
}

export async function listDevices(): Promise<Device[]> {
    const response = await api.get("/api/devices");
    return listOf(payloadOf(response), "devices").map(normalizeDevice);
}

export async function getDevice(id: string): Promise<Device> {
    const response = await api.get(`/api/devices/${encodeURIComponent(id)}`);
    return normalizeDevice(payloadOf(response).device);
}

export async function createDevice(input: CreateDeviceInput): Promise<Device> {
    const response = await api.post("/api/devices", input);
    return normalizeDevice(payloadOf(response).device);
}

export async function updateDevice(id: string, patch: Partial<CreateDeviceInput>): Promise<Device> {
    const response = await api.patch(`/api/devices/${encodeURIComponent(id)}`, patch);
    return normalizeDevice(payloadOf(response).device);
}

export async function deleteDevice(id: string): Promise<void> {
    await api.delete(`/api/devices/${encodeURIComponent(id)}`);
}

export async function detectDevice(id: string): Promise<DetectionResult> {
    const response = await api.post(`/api/devices/${encodeURIComponent(id)}/detect`);
    return normalizeDetection(payloadOf(response).detection);
}

export async function identifyDevice(id: string): Promise<Device> {
    const response = await api.post(`/api/devices/${encodeURIComponent(id)}/identify`);
    return normalizeDevice(payloadOf(response).device);
}

export async function searchRecordings(id: string, input: RecordingSearchInput): Promise<RecordingIndex> {
    const response = await api.post(`/api/devices/${encodeURIComponent(id)}/recordings/search`, input);
    return normalizeRecordingIndex(payloadOf(response).index);
}

export async function listRecordings(id: string): Promise<RecordingIndex> {
    const response = await api.get(`/api/devices/${encodeURIComponent(id)}/recordings`, { silentToast: true });
    const payload = payloadOf(response);
    return normalizeRecordingIndex(payload.index ?? payload);
}

export async function createAcquisition(id: string, input: AcquisitionInput): Promise<void> {
    await api.post(`/api/devices/${encodeURIComponent(id)}/acquisitions`, input);
}

export async function listCustody(id: string, options: { silent?: boolean } = {}): Promise<CustodyEvent[]> {
    const response = await api.get(`/api/devices/${encodeURIComponent(id)}/custody`, { silentToast: options.silent ?? false });
    return listOf(payloadOf(response), "events").map(normalizeCustodyEvent);
}

export async function runAnalysis(id: string): Promise<AnalysisReport> {
    const response = await api.post(`/api/devices/${encodeURIComponent(id)}/analysis`);
    return normalizeAnalysis(payloadOf(response));
}

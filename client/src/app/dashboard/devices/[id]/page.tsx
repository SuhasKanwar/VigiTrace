import type { Metadata } from "next";
import { redirect } from "next/navigation";
import DeviceDetail from "@/components/devices/device-detail";
import { getAuthSession } from "@/lib/session";

export const metadata: Metadata = { title: "Device record · VigiTrace" };

export default async function DevicePage({ params }: { params: Promise<{ id: string }> }) {
    if (!await getAuthSession()) redirect("/auth/signin");
    const { id } = await params;
    return <DeviceDetail deviceId={id} />;
}

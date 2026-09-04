import type { Metadata } from "next";
import { redirect } from "next/navigation";
import DeviceList from "@/components/devices/device-list";
import { getAuthSession } from "@/lib/session";

export const metadata: Metadata = { title: "Devices · VigiTrace" };

export default async function DevicesPage() {
    if (!await getAuthSession()) redirect("/auth/signin");
    return <DeviceList />;
}

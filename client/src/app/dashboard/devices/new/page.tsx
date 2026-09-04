import type { Metadata } from "next";
import { redirect } from "next/navigation";
import DeviceForm from "@/components/devices/device-form";
import { getAuthSession } from "@/lib/session";

export const metadata: Metadata = { title: "Add device · VigiTrace" };

export default async function NewDevicePage() {
    if (!await getAuthSession()) redirect("/auth/signin");
    return <DeviceForm />;
}

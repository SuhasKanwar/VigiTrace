import type { Metadata } from "next";
import { redirect } from "next/navigation";
import DashboardOverview from "@/components/dashboard/overview";
import { getAuthSession } from "@/lib/session";

export const metadata: Metadata = { title: "Overview · VigiTrace" };

export default async function DashboardPage() {
    if (!await getAuthSession()) redirect("/auth/signin");
    return <DashboardOverview />;
}

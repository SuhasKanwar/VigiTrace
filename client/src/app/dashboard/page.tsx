import { redirect } from "next/navigation";
import { getAuthSession } from "@/lib/session";

export default async function DashboardPage() {
    if (!await getAuthSession()) redirect("/auth/signin");
    return null;
}

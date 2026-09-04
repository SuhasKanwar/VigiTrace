import StatusScreen from "@/components/ui/status-screen";
import Link from "next/link";
import { MapPinOff } from "lucide-react";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Page not found · VigiTrace" };

export default function NotFoundPage() {
    return (
        <StatusScreen
            action={<Link className="rounded-xl bg-(--primary-color) px-4 py-2.5 text-sm font-semibold text-(--surface-color) transition-colors hover:bg-(--secondary-color)" href="/">Return home</Link>}
            description="The page you requested does not exist or may have moved."
            eyebrow="404 · Not found"
            icon={<MapPinOff aria-hidden="true" className="size-5" />}
            title="This route is off the map"
        />
    );
}

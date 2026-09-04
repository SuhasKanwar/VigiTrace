import Link from "next/link";
import { ArrowRight, CircleAlert } from "lucide-react";
import StatusScreen from "@/components/ui/status-screen";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Authentication problem · VigiTrace" };

export default function AuthErrorPage() {
    return <StatusScreen action={<><Link className="inline-flex items-center gap-2 bg-(--primary-color) px-4 py-2.5 text-sm font-semibold text-(--surface-color) transition-colors hover:bg-(--secondary-color)" href="/auth/signin">Try signing in <ArrowRight aria-hidden="true" className="size-4" /></Link><Link className="border border-(--border-color) px-4 py-2.5 text-sm font-semibold transition-colors hover:bg-(--surface-muted-color)" href="/">Return home</Link></>} description="The identity provider could not complete this request. No case or evidence data was changed." eyebrow="Authentication interrupted" icon={<CircleAlert aria-hidden="true" className="size-5" />} title="We could not verify your account" />;
}

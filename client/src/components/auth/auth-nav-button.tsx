"use client";

import { ArrowRight } from "lucide-react";
import { useSession } from "next-auth/react";
import Link from "next/link";

export default function AuthNavButton() {
    const { status } = useSession();
    const authenticated = status === "authenticated";

    return (
        <div className="flex items-center gap-2">
            {!authenticated && status !== "loading" ? <Link className="hidden px-3 py-2 text-sm font-semibold text-(--secondary-text-color) transition-colors hover:text-(--primary-text-color) sm:inline-flex" href="/auth/signup">Create account</Link> : null}
            <Link aria-disabled={status === "loading"} className="inline-flex items-center gap-2 bg-(--primary-color) px-4 py-2 text-sm font-semibold text-(--surface-color) transition-colors hover:bg-(--secondary-color) aria-disabled:pointer-events-none aria-disabled:opacity-60" href={authenticated ? "/dashboard" : "/auth/signin"}>{status === "loading" ? "Checking" : authenticated ? "Dashboard" : "Sign in"}<ArrowRight aria-hidden="true" className="size-4" /></Link>
        </div>
    );
}

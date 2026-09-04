"use client";

import { ArrowRight, LogOut } from "lucide-react";
import { signOut, useSession } from "next-auth/react";
import Link from "next/link";

export default function AuthNavButton() {
    const { data, status } = useSession();
    const authenticated = status === "authenticated";

    if (status === "loading") return <span aria-label="Checking session" className="h-10 w-24 animate-loading-pulse bg-(--surface-strong-color)" />;

    return (
        <div className="flex items-center gap-2">
            {!authenticated ? <Link className="hidden border border-(--border-color) px-4 py-2 text-sm font-semibold transition-colors hover:bg-(--surface-muted-color) sm:inline-flex" href="/auth/signup">Create account</Link> : null}
            <Link className="inline-flex items-center gap-2 bg-(--primary-color) px-4 py-2 text-sm font-semibold text-(--surface-color) transition-colors hover:bg-(--secondary-color)" href={authenticated ? "/dashboard" : "/auth/signin"}>{authenticated ? <span className="grid size-5 place-items-center rounded-full bg-(--surface-color) text-xs font-bold text-(--primary-color)">{data.user?.name?.charAt(0).toUpperCase() ?? "V"}</span> : null}{authenticated ? "Workspace" : "Sign in"}<ArrowRight aria-hidden="true" className="size-4" /></Link>
            {authenticated ? <button className="inline-flex items-center gap-2 border border-(--border-color) px-3 py-2 text-sm font-semibold text-(--secondary-text-color) transition-colors hover:bg-(--surface-muted-color) hover:text-(--primary-text-color)" onClick={() => signOut({ callbackUrl: "/" })} type="button"><LogOut aria-hidden="true" className="size-4" /><span className="hidden sm:inline">Sign out</span></button> : null}
        </div>
    );
}

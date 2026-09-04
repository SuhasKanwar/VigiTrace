"use client";

import { LogOut } from "lucide-react";
import { signOut } from "next-auth/react";

export default function SignOutButton() {
    return <button className="inline-flex items-center gap-2 border border-(--border-color) px-4 py-2 text-sm font-semibold transition-colors hover:bg-(--surface-muted-color)" onClick={() => signOut({ callbackUrl: "/" })} type="button"><LogOut aria-hidden="true" className="size-4" />Sign out</button>;
}

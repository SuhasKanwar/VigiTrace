"use client";

import { SessionProvider } from "next-auth/react";
import type { Session } from "next-auth";
import { ToastProvider } from "@/components/ui/toast";

export default function Provider({ children, session }: { children: React.ReactNode; session: Session | null; }) {
    return (
        <SessionProvider session={session}>
            <ToastProvider>{children}</ToastProvider>
        </SessionProvider>
    );
}
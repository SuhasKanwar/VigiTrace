import { redirect } from "next/navigation";
import AuthForm from "@/components/auth/auth-form";
import { getAuthSession } from "@/lib/session";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Create account · VigiTrace" };

export default async function SignUpPage() {
    if (await getAuthSession()) redirect("/dashboard");
    return <AuthForm mode="signup" />;
}

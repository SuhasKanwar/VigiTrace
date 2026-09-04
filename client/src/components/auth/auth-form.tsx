"use client";

import { ArrowRight, Check, LoaderCircle, LockKeyhole } from "lucide-react";
import { signIn } from "next-auth/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { type FormEvent, useState } from "react";
import { AUTH_CALLBACK_URL } from "@/lib/config";
import Logo from "@/components/ui/logo";

export default function AuthForm({ mode }: { mode: "signin" | "signup" }) {
    const signup = mode === "signup";
    const router = useRouter();
    const [error, setError] = useState("");
    const [pending, setPending] = useState(false);

    async function submit(event: FormEvent<HTMLFormElement>) {
        event.preventDefault();
        setPending(true);
        setError("");
        const form = new FormData(event.currentTarget);
        const result = await signIn("credentials", {
            redirect: false,
            name: form.get("name"),
            email: form.get("email"),
            password: form.get("password"),
            register: String(signup),
            callbackUrl: AUTH_CALLBACK_URL,
        });

        if (!result?.ok) {
            setError(signup ? "Could not create the account. Check your details and try again." : "Email or password is incorrect.");
            setPending(false);
            return;
        }

        router.push(result.url ?? AUTH_CALLBACK_URL);
        router.refresh();
    }

    return (
        <main className="flex min-h-screen items-center justify-center px-5 py-10">
            <section className="grid w-full max-w-5xl overflow-hidden border border-(--border-color) bg-(--surface-color) shadow-[0_28px_80px_var(--shadow-color)] lg:grid-cols-[.9fr_1.1fr]">
                <aside className="relative flex min-h-72 flex-col justify-between overflow-hidden bg-(--mechanism-color) p-8 text-(--surface-color) sm:p-12">
                    <Logo inverse />
                    <div className="relative mt-16">
                        <p className="font-mono text-xs font-semibold uppercase tracking-[.18em] text-(--secondary-color)">Protected evidence workspace</p>
                        <h1 className="mt-4 max-w-md text-4xl font-bold tracking-[-.045em] sm:text-5xl">The investigation starts with a trusted record.</h1>
                        <div className="mt-9 space-y-3 text-sm text-(--muted-text-color)">
                            {["Case activity stays attributable", "Evidence integrity remains visible", "Access is tied to the investigator"].map((item) => <p className="flex items-center gap-3" key={item}><Check aria-hidden="true" className="size-4 text-(--secondary-color)" />{item}</p>)}
                        </div>
                    </div>
                    <LockKeyhole aria-hidden="true" className="absolute -bottom-10 -right-8 size-52 text-(--mechanism-edge)" strokeWidth={0.7} />
                </aside>

                <div className="p-8 sm:p-12 lg:p-16">
                    <p className="font-mono text-xs font-semibold uppercase tracking-[.18em] text-(--primary-color)">{signup ? "Create investigator account" : "Investigator access"}</p>
                    <h2 className="mt-3 text-3xl font-bold tracking-[-.04em]">{signup ? "Create your workspace" : "Welcome back"}</h2>
                    <p className="mt-3 text-sm leading-6 text-(--secondary-text-color)">{signup ? "Set up your account to begin a defensible evidence workflow." : "Sign in to continue to your evidence workspace."}</p>

                    <button className="mt-8 flex w-full items-center justify-center gap-3 border border-(--border-color) px-4 py-3 text-sm font-semibold transition-colors hover:bg-(--surface-muted-color) disabled:cursor-not-allowed disabled:opacity-60" disabled={pending} onClick={() => signIn("google", { callbackUrl: AUTH_CALLBACK_URL })} type="button">Continue with Google</button>
                    <div className="my-7 flex items-center gap-4 text-[10px] uppercase tracking-[.16em] text-(--muted-text-color)"><span className="h-px flex-1 bg-(--border-color)" />or use email<span className="h-px flex-1 bg-(--border-color)" /></div>

                    <form className="space-y-5" onSubmit={submit}>
                        {signup ? <label className="block text-sm font-semibold">Full name<input autoComplete="name" className="mt-2 w-full border border-(--border-color) bg-(--primary-bg-color) px-4 py-3 font-normal outline-none transition-colors focus:border-(--primary-color)" name="name" placeholder="Investigator name" required type="text" /></label> : null}
                        <label className="block text-sm font-semibold">Email address<input autoComplete="email" className="mt-2 w-full border border-(--border-color) bg-(--primary-bg-color) px-4 py-3 font-normal outline-none transition-colors focus:border-(--primary-color)" name="email" placeholder="name@agency.gov" required type="email" /></label>
                        <label className="block text-sm font-semibold">Password<input autoComplete={signup ? "new-password" : "current-password"} className="mt-2 w-full border border-(--border-color) bg-(--primary-bg-color) px-4 py-3 font-normal outline-none transition-colors focus:border-(--primary-color)" name="password" placeholder="Enter your password" required type="password" /></label>
                        {error ? <p aria-live="polite" className="border-l-2 border-(--danger-color) bg-(--surface-muted-color) px-4 py-3 text-sm text-(--danger-color)">{error}</p> : null}
                        <button className="flex w-full items-center justify-center gap-2 bg-(--primary-color) px-5 py-3 text-sm font-semibold text-(--surface-color) transition-colors hover:bg-(--secondary-color) disabled:cursor-not-allowed disabled:opacity-60" disabled={pending} type="submit">{pending ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : <ArrowRight aria-hidden="true" className="size-4" />}{pending ? "Please wait" : signup ? "Create account" : "Sign in"}</button>
                    </form>

                    <p className="mt-7 text-center text-sm text-(--secondary-text-color)">{signup ? "Already have an account?" : "New to VigiTrace?"} <Link className="font-semibold text-(--primary-color) hover:text-(--secondary-color)" href={signup ? "/auth/signin" : "/auth/signup"}>{signup ? "Sign in" : "Create an account"}</Link></p>
                </div>
            </section>
        </main>
    );
}

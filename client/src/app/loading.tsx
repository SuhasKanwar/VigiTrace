import Logo from "@/components/ui/logo";

export default function Loading() {
    return (
        <main aria-busy="true" aria-label="Loading page" className="flex min-h-screen flex-1 items-center justify-center px-5 py-10">
            <div className="animate-screen-enter w-full max-w-xl border border-(--border-color) border-l-4 border-l-(--primary-color) bg-(--surface-color) p-8 sm:p-10">
                <Logo />
                <div className="mt-12 animate-loading-pulse space-y-4">
                    <div className="h-3 w-24 rounded-full bg-(--surface-strong-color)" />
                    <div className="h-10 w-3/4 bg-(--surface-strong-color)" />
                    <div className="h-5 w-full rounded-full bg-(--surface-muted-color)" />
                    <div className="h-5 w-5/6 rounded-full bg-(--surface-muted-color)" />
                </div>
            </div>
        </main>
    );
}

export default function Loading() {
    return (
        <main aria-busy="true" aria-label="Loading page" className="flex min-h-screen flex-1 items-center justify-center px-5 py-10">
            <div className="animate-screen-enter w-full max-w-xl rounded-3xl border border-(--border-color) bg-(--surface-color)/90 p-8 shadow-[0_24px_70px_var(--shadow-color)] backdrop-blur sm:p-10">
                <div className="animate-loading-pulse size-10 rounded-xl bg-(--primary-color)" />
                <div className="mt-12 animate-loading-pulse space-y-4">
                    <div className="h-3 w-24 rounded-full bg-(--surface-strong-color)" />
                    <div className="h-10 w-3/4 rounded-xl bg-(--surface-strong-color)" />
                    <div className="h-5 w-full rounded-full bg-(--surface-muted-color)" />
                    <div className="h-5 w-5/6 rounded-full bg-(--surface-muted-color)" />
                </div>
            </div>
        </main>
    );
}

import Logo from "@/components/ui/logo";
import AuthNavButton from "@/components/auth/auth-nav-button";

export default function Navbar() {
    return (
        <header className="sticky top-0 z-50 border-b border-(--border-color) bg-(--surface-color)">
            <nav aria-label="Main navigation" className="mx-auto flex max-w-7xl items-center justify-between gap-6 px-5 py-3 lg:px-8">
                <Logo />
                <div className="hidden items-center border border-(--border-color) bg-(--primary-bg-color) p-1 text-sm font-medium text-(--secondary-text-color) md:flex">
                    <a className="px-4 py-2 transition-colors hover:bg-(--surface-strong-color) hover:text-(--primary-text-color)" href="#network">Network</a>
                    <a className="px-4 py-2 transition-colors hover:bg-(--surface-strong-color) hover:text-(--primary-text-color)" href="#workflow">Workflow</a>
                    <a className="px-4 py-2 transition-colors hover:bg-(--surface-strong-color) hover:text-(--primary-text-color)" href="#analysis">Analysis</a>
                    <a className="px-4 py-2 transition-colors hover:bg-(--surface-strong-color) hover:text-(--primary-text-color)" href="#integrity">Integrity</a>
                </div>
                <AuthNavButton />
            </nav>
        </header>
    );
}

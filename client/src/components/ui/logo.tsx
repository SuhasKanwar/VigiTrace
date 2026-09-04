import Link from "next/link";

export default function Logo({ inverse = false, display = false, className = "" }: { inverse?: boolean; display?: boolean; className?: string }) {
    return (
        <Link aria-label="VigiTrace home" className={`inline-flex items-center gap-2 font-bold tracking-[-.04em] ${display ? "text-[clamp(4rem,14vw,11rem)] leading-none" : "text-base"} ${className}`} href="/">
            <span><span className="text-(--primary-color)">Vigi</span><span className={inverse ? "text-(--surface-color)" : "text-(--primary-text-color)"}>Trace</span></span>
        </Link>
    );
}

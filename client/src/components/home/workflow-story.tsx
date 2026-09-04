"use client";

import { BrainCircuit, FileCheck2, FileSearch, HardDriveDownload, ScanSearch } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const STEPS = [
    { title: "Identify", eyebrow: "01 · Device profile", description: "Recognize the recorder family, storage layout, channels, and clock state before touching the source media.", detail: "Hardware and firmware context captured first.", background: "var(--surface-muted-color)", Icon: ScanSearch },
    { title: "Acquire", eyebrow: "02 · Forensic intake", description: "Capture a defensible image and record every operator action from the first connection.", detail: "Source media preserved with cryptographic hashes.", background: "var(--surface-strong-color)", Icon: HardDriveDownload },
    { title: "Recover", eyebrow: "03 · Reconstruction", description: "Parse proprietary storage, locate fragmented recordings, and rebuild footage ordinary playback cannot show.", detail: "Recovered segments remain linked to their source.", background: "var(--accent-color)", Icon: FileSearch },
    { title: "Analyze", eyebrow: "04 · Correlation", description: "Normalize time, correlate cameras, and surface the events worth an investigator’s attention.", detail: "Every finding leads back to the original frame.", background: "var(--surface-muted-color)", Icon: BrainCircuit },
    { title: "Report", eyebrow: "05 · Case output", description: "Package findings, verification records, timelines, and custody history into one consistent case report.", detail: "Review decisions remain reproducible and explainable.", background: "var(--surface-strong-color)", Icon: FileCheck2 },
];

export default function WorkflowStory() {
    const [activeStep, setActiveStep] = useState(0);
    const cardRefs = useRef<(HTMLElement | null)[]>([]);
    const step = STEPS[activeStep];
    const ActiveIcon = step.Icon;

    useEffect(() => {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) setActiveStep(Number(entry.target.getAttribute("data-step")));
            });
        }, { rootMargin: "-35% 0px -35% 0px" });

        cardRefs.current.forEach((card) => card && observer.observe(card));
        return () => observer.disconnect();
    }, []);

    return (
        <section className="border-y border-(--border-color)" id="workflow">
            <div className="mx-auto max-w-7xl px-5 lg:px-8">
                <div className="grid gap-10 lg:grid-cols-2 lg:gap-0">
                    <div className="space-y-[14vh] py-20 lg:pr-12">
                        {STEPS.map((item, index) => <article aria-current={index === activeStep ? "step" : undefined} className={`flex min-h-[62vh] items-center border border-(--border-color) p-8 transition-[opacity,transform] duration-500 sm:p-12 ${index === activeStep ? "scale-100 opacity-100" : "scale-[.98] opacity-70"}`} data-step={index} key={item.title} ref={(element) => { cardRefs.current[index] = element; }} style={{ backgroundColor: item.background }}><div className="max-w-md"><p className="font-mono text-xs font-semibold uppercase tracking-[.18em] text-(--primary-color)">{item.eyebrow}</p><item.Icon aria-hidden="true" className="mt-10 size-9" /><h3 className="mt-6 text-3xl font-bold tracking-[-.04em] sm:text-4xl">{item.title} without gaps.</h3><p className="mt-5 leading-8 text-(--secondary-text-color)">{item.description}</p><p className="mt-8 border-l-2 border-(--primary-color) pl-4 text-sm font-semibold">{item.detail}</p></div></article>)}
                    </div>
                    <aside className="self-start border-x border-(--border-color) bg-(--surface-color) lg:sticky lg:top-0 lg:flex lg:h-screen lg:items-center">
                        <div className="w-full p-8 sm:p-12 lg:p-16">
                            <p className="font-mono text-xs font-semibold uppercase tracking-[.18em] text-(--primary-color)">One defensible workflow</p>
                            <div className="mt-10 flex gap-5">
                                <div className="relative w-px bg-(--border-color)"><div className="absolute left-0 top-0 w-px bg-(--primary-color) transition-all duration-500" style={{ height: `${((activeStep + 1) / STEPS.length) * 100}%` }} /></div>
                                <div className="space-y-6">{STEPS.map((item, index) => <div className={`transition-colors duration-300 ${index === activeStep ? "text-(--primary-text-color)" : "text-(--muted-text-color)"}`} key={item.title}><p className="font-mono text-xs">{item.eyebrow}</p><p className="mt-1 text-sm font-semibold">{item.title}</p></div>)}</div>
                            </div>
                            <div className="mt-14" key={step.title}><ActiveIcon aria-hidden="true" className="animate-screen-enter size-8 text-(--primary-color)" /><h2 className="animate-screen-enter mt-6 text-4xl font-bold tracking-[-.04em] sm:text-5xl">{step.title}, with the record intact.</h2><p className="animate-screen-enter mt-5 max-w-md leading-8 text-(--secondary-text-color)">{step.detail}</p></div>
                        </div>
                    </aside>
                </div>
            </div>
        </section>
    );
}

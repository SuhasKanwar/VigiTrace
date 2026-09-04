"use client";

import { BrainCircuit, FileSearch, HardDriveDownload } from "lucide-react";
import { useEffect, useRef, useState } from "react";

const STEPS = [
    { title: "Acquire", eyebrow: "01 · Intake", description: "Identify the recorder, capture a defensible image, and record every operator action from the first connection.", detail: "Device profile and source media preserved.", background: "var(--surface-muted-color)", Icon: HardDriveDownload },
    { title: "Recover", eyebrow: "02 · Reconstruction", description: "Parse proprietary storage, locate fragmented recordings, and rebuild the footage that ordinary playback cannot show.", detail: "Recovered segments remain linked to their source.", background: "var(--accent-color)", Icon: FileSearch },
    { title: "Analyze", eyebrow: "03 · Review", description: "Normalize time, correlate cameras, and surface the events worth an investigator’s attention.", detail: "Every finding leads back to the original frame.", background: "var(--surface-strong-color)", Icon: BrainCircuit },
];

export default function WorkflowStory() {
    const [activeStep, setActiveStep] = useState(0);
    const cardRefs = useRef<(HTMLElement | null)[]>([]);
    const step = STEPS[activeStep];

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
                <div className="grid lg:grid-cols-2">
                    <div className="lg:sticky lg:top-0 lg:flex lg:h-screen lg:items-center" style={{ backgroundColor: step.background }}>
                        <div className="w-full border-x border-(--border-color) p-8 transition-colors duration-500 sm:p-12 lg:p-16">
                            <p className="font-mono text-xs font-semibold uppercase tracking-[.18em] text-(--primary-color)">One defensible workflow</p>
                            <div className="mt-10 flex gap-5">
                                <div className="relative w-px bg-(--border-color)"><div className="absolute left-0 top-0 w-px bg-(--primary-color) transition-all duration-500" style={{ height: `${((activeStep + 1) / STEPS.length) * 100}%` }} /></div>
                                <div className="space-y-6">{STEPS.map((item, index) => <div className={index === activeStep ? "text-(--primary-text-color)" : "text-(--muted-text-color)"} key={item.title}><p className="font-mono text-xs">{item.eyebrow}</p><p className="mt-1 text-sm font-semibold">{item.title}</p></div>)}</div>
                            </div>
                            <div className="mt-14"><step.Icon aria-hidden="true" className="size-8 text-(--primary-color)" /><h2 className="mt-6 text-4xl font-bold tracking-[-.04em] sm:text-5xl">{step.title}, with the record intact.</h2><p className="mt-5 max-w-md leading-8 text-(--secondary-text-color)">{step.detail}</p></div>
                        </div>
                    </div>
                    <div className="border-r border-(--border-color)">{STEPS.map((item, index) => <article className="flex min-h-[70svh] items-center border-b border-(--border-color) p-8 sm:p-12 lg:min-h-screen lg:p-16" data-step={index} key={item.title} ref={(element) => { cardRefs.current[index] = element; }}><div className="max-w-md"><p className="font-mono text-xs font-semibold uppercase tracking-[.18em] text-(--primary-color)">{item.eyebrow}</p><item.Icon aria-hidden="true" className="mt-10 size-9" /><h3 className="mt-6 text-3xl font-bold tracking-[-.04em]">{item.title} without gaps.</h3><p className="mt-5 leading-8 text-(--secondary-text-color)">{item.description}</p><p className="mt-8 border-l-2 border-(--primary-color) pl-4 text-sm font-semibold">{item.detail}</p></div></article>)}</div>
                </div>
            </div>
        </section>
    );
}

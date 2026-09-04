import { ArrowRight, BrainCircuit, Check, CircleCheck, Clock3, FileSearch, Fingerprint, HardDriveDownload, LockKeyhole, Play, Sparkles } from "lucide-react";
import ForensicGlobe from "@/components/ui/forensic-globe";
import WorkflowStory from "@/components/home/workflow-story";
import Logo from "@/components/ui/logo";
import AuthNavButton from "@/components/auth/auth-nav-button";

export default function Home() {
  return (
    <main className="overflow-x-clip">
      <header className="sticky top-0 z-50 border-b border-(--border-color) bg-(--surface-color)">
        <nav aria-label="Main navigation" className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4 lg:px-8">
          <Logo />
          <div className="hidden items-center gap-7 text-sm font-medium text-(--secondary-text-color) md:flex">
            <a className="transition-colors hover:text-(--primary-text-color)" href="#workflow">Workflow</a>
            <a className="transition-colors hover:text-(--primary-text-color)" href="#analysis">Analysis</a>
            <a className="transition-colors hover:text-(--primary-text-color)" href="#integrity">Integrity</a>
          </div>
          <AuthNavButton />
        </nav>
      </header>

      <section className="border-b border-(--border-color) bg-(--surface-color)">
        <div className="mx-auto grid max-w-7xl gap-14 px-5 py-20 lg:grid-cols-[1.05fr_.95fr] lg:px-8 lg:py-28">
          <div className="flex max-w-2xl flex-col justify-center">
            <p className="font-mono text-xs font-semibold uppercase tracking-[.18em] text-(--primary-color)">Video evidence, made verifiable</p>
            <h1 className="mt-5 text-5xl font-bold tracking-[-.055em] sm:text-6xl lg:text-7xl">Trace every frame. Defend every finding.</h1>
            <p className="mt-7 max-w-xl text-lg leading-8 text-(--secondary-text-color)">A single forensic workspace for acquiring, recovering, analyzing, and reporting surveillance evidence across DVR and NVR vendors.</p>
            <div className="mt-9 flex flex-wrap gap-3">
              <a className="inline-flex items-center gap-2 bg-(--primary-color) px-5 py-3 text-sm font-semibold text-(--surface-color) transition-colors hover:bg-(--secondary-color)" href="#workflow">See the workflow <ArrowRight aria-hidden="true" className="size-4" /></a>
              <a className="inline-flex items-center gap-2 border border-(--border-color) px-5 py-3 text-sm font-semibold transition-colors hover:bg-(--surface-muted-color)" href="#analysis"><Play aria-hidden="true" className="size-4" /> Watch overview</a>
            </div>
            <div className="mt-12 flex flex-wrap gap-x-8 gap-y-4 border-t border-(--border-color) pt-6 text-sm text-(--secondary-text-color)">
              <span className="flex items-center gap-2"><Check aria-hidden="true" className="size-4 text-(--success-color)" />Vendor-agnostic intake</span>
              <span className="flex items-center gap-2"><Check aria-hidden="true" className="size-4 text-(--success-color)" />Hash-backed evidence trail</span>
            </div>
          </div>

          <div className="reveal-on-scroll self-center border border-(--border-color) bg-(--primary-bg-color) p-5 sm:p-7">
            <div className="flex items-center justify-between border-b border-(--border-color) pb-4">
              <div><p className="font-mono text-[11px] font-semibold uppercase tracking-[.16em] text-(--muted-text-color)">Active evidence set</p><p className="mt-1 text-sm font-semibold">Riverside precinct · 04</p></div>
              <span className="flex items-center gap-2 text-xs font-semibold text-(--success-color)"><span className="size-2 rounded-full bg-(--success-color)" />Verified</span>
            </div>
            <div className="mt-6 grid grid-cols-[auto_1fr] gap-x-4 gap-y-5">
              <div className="grid size-10 place-items-center bg-(--surface-strong-color) text-(--primary-color)"><HardDriveDownload aria-hidden="true" className="size-5" /></div><div><p className="text-sm font-semibold">Acquisition complete</p><p className="mt-1 text-xs text-(--secondary-text-color)">Dahua NVR · 12 channels · 1.84 TB</p></div>
              <div className="grid size-10 place-items-center bg-(--surface-strong-color) text-(--primary-color)"><FileSearch aria-hidden="true" className="size-5" /></div><div><p className="text-sm font-semibold">1,248 recordings indexed</p><p className="mt-1 text-xs text-(--secondary-text-color)">Timeline normalized to UTC+05:30</p></div>
              <div className="grid size-10 place-items-center bg-(--surface-strong-color) text-(--primary-color)"><BrainCircuit aria-hidden="true" className="size-5" /></div><div><p className="text-sm font-semibold">14 events need review</p><p className="mt-1 text-xs text-(--secondary-text-color)">Motion, person, and vehicle detections</p></div>
            </div>
            <div className="mt-7 border-t border-(--border-color) pt-5"><div className="flex items-center justify-between text-xs"><span className="font-mono text-(--secondary-text-color)">SHA-256</span><span className="font-mono text-(--success-color)">MATCHED</span></div><div className="mt-3 h-2 bg-(--surface-strong-color)"><div className="h-full w-4/5 bg-(--primary-color)" /></div></div>
          </div>
        </div>
      </section>

      <section className="border-b border-(--border-color) bg-(--surface-muted-color)">
        <div className="mx-auto grid max-w-7xl grid-cols-2 divide-x divide-(--border-color) px-5 sm:grid-cols-4 lg:px-8">
          {[['08', 'major OEM families'], ['24/7', 'evidence continuity'], ['SHA-256', 'integrity checks'], ['UTC', 'normalized timeline']].map(([value, label]) => <div className="py-8 text-center sm:py-10" key={label}><p className="text-2xl font-semibold tracking-tight">{value}</p><p className="mt-1 text-xs text-(--secondary-text-color)">{label}</p></div>)}
        </div>
      </section>

      <section className="overflow-hidden border-b border-(--border-color) bg-(--surface-color)" id="network">
        <div className="mx-auto grid max-w-7xl items-center gap-12 px-5 py-20 lg:grid-cols-[.85fr_1.15fr] lg:px-8">
          <div className="reveal-on-scroll"><p className="font-mono text-xs font-semibold uppercase tracking-[.18em] text-(--primary-color)">Designed for distributed evidence</p><h2 className="mt-4 text-4xl font-bold tracking-[-.04em] sm:text-5xl">One case view, across every location.</h2><p className="mt-6 max-w-lg leading-8 text-(--secondary-text-color)">Bring cameras, recorders, exported media, and investigator notes into a single review context—without losing the device-level detail behind them.</p><div className="mt-8 space-y-3 text-sm font-medium"><p className="flex items-center gap-3"><Check aria-hidden="true" className="size-4 text-(--success-color)" />Multi-site acquisition tracking</p><p className="flex items-center gap-3"><Check aria-hidden="true" className="size-4 text-(--success-color)" />Cross-camera event correlation</p></div></div>
          <div className="reveal-on-scroll relative h-112 overflow-hidden border border-(--border-color)"><ForensicGlobe /><div className="absolute bottom-6 left-6 border border-(--border-color) bg-(--surface-color) px-4 py-3 text-sm shadow-[0_14px_36px_var(--shadow-color)]"><p className="font-mono text-[10px] uppercase tracking-[.14em] text-(--muted-text-color)">Network status</p><p className="mt-1 flex items-center gap-2 font-semibold"><span className="size-2 rounded-full bg-(--success-color)" />8 sites connected</p></div></div>
        </div>
      </section>

      <WorkflowStory />

      <section className="border-y border-(--border-color) bg-(--mechanism-color) text-(--surface-color)" id="analysis">
        <div className="mx-auto grid max-w-7xl gap-14 px-5 py-24 lg:grid-cols-2 lg:px-8">
          <div className="reveal-on-scroll"><p className="font-mono text-xs font-semibold uppercase tracking-[.18em] text-(--secondary-color)">Intelligence at review time</p><h2 className="mt-4 text-4xl font-bold tracking-[-.04em] sm:text-5xl">Find the moment that matters.</h2><p className="mt-6 max-w-lg leading-8 text-(--muted-text-color)">Use machine-assisted person, object, and motion detections as a review aid—then retain the source footage and audit trail behind every conclusion.</p><a className="mt-9 inline-flex items-center gap-2 border border-(--mechanism-line) px-5 py-3 text-sm font-semibold transition-colors hover:bg-(--mechanism-edge)" href="#integrity">Explore analysis <ArrowRight aria-hidden="true" className="size-4" /></a></div>
          <div className="reveal-on-scroll border border-(--border-color) bg-(--surface-color) p-5 text-(--primary-text-color) shadow-[0_24px_70px_var(--shadow-color)] sm:p-7"><div className="flex items-center justify-between border-b border-(--border-color) pb-4"><div><span className="font-mono text-xs uppercase tracking-[.14em] text-(--secondary-text-color)">Camera 07 · 22:14:08</span><p className="mt-1 text-sm font-semibold">Loading bay · East entrance</p></div><span className="grid size-9 place-items-center bg-(--surface-strong-color)"><Sparkles aria-hidden="true" className="size-4 text-(--primary-color)" /></span></div><div className="relative mt-6 aspect-video overflow-hidden border border-(--border-color) bg-(--surface-muted-color)"><div className="absolute inset-x-0 bottom-0 h-1/3 border-t border-(--border-color) bg-(--surface-strong-color)" /><div className="absolute bottom-1/3 right-[12%] h-[44%] w-[22%] border-x border-t border-(--border-color) bg-(--surface-color)" /><div className="absolute left-[26%] top-[18%] h-[58%] w-[24%] border-2 border-(--primary-color)" /><span className="absolute left-[26%] top-[7%] bg-(--primary-color) px-2 py-1 font-mono text-[10px] font-bold text-(--surface-color)">PERSON · 98%</span><div className="absolute inset-x-4 bottom-4 h-1 bg-(--surface-color)"><div className="h-full w-2/3 bg-(--primary-color)" /></div></div><div className="mt-5 grid grid-cols-3 gap-3 text-center"><div><p className="text-lg font-semibold">14</p><p className="mt-1 text-[11px] uppercase tracking-wide text-(--secondary-text-color)">Events</p></div><div className="border-x border-(--border-color)"><p className="text-lg font-semibold">03:12</p><p className="mt-1 text-[11px] uppercase tracking-wide text-(--secondary-text-color)">Duration</p></div><div><p className="text-lg font-semibold">4</p><p className="mt-1 text-[11px] uppercase tracking-wide text-(--secondary-text-color)">Cameras</p></div></div></div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-5 py-24 lg:px-8" id="integrity">
        <div className="grid gap-14 lg:grid-cols-[.9fr_1.1fr]"><div className="reveal-on-scroll"><p className="font-mono text-xs font-semibold uppercase tracking-[.18em] text-(--primary-color)">Integrity is built in</p><h2 className="mt-4 text-4xl font-bold tracking-[-.04em] sm:text-5xl">Evidence you can account for.</h2><p className="mt-6 max-w-md leading-8 text-(--secondary-text-color)">Every acquisition is paired with the records needed to reproduce, verify, and explain it.</p></div><div className="reveal-on-scroll divide-y divide-(--border-color) border-y border-(--border-color)"><div className="flex gap-5 py-6"><Fingerprint aria-hidden="true" className="mt-1 size-5 shrink-0 text-(--primary-color)" /><div><h3 className="font-semibold">Cryptographic verification</h3><p className="mt-2 leading-7 text-(--secondary-text-color)">MD5 and SHA-256 hashes document image and export integrity.</p></div></div><div className="flex gap-5 py-6"><Clock3 aria-hidden="true" className="mt-1 size-5 shrink-0 text-(--primary-color)" /><div><h3 className="font-semibold">Normalized chronology</h3><p className="mt-2 leading-7 text-(--secondary-text-color)">Recorded timestamps are reconciled into one investigation timeline.</p></div></div><div className="flex gap-5 py-6"><LockKeyhole aria-hidden="true" className="mt-1 size-5 shrink-0 text-(--primary-color)" /><div><h3 className="font-semibold">Chain of custody</h3><p className="mt-2 leading-7 text-(--secondary-text-color)">Operator actions and evidence handoffs stay linked to the case record.</p></div></div></div></div>
      </section>

      <section className="border-t border-(--border-color) bg-(--surface-muted-color)"><div className="mx-auto flex max-w-7xl flex-col items-start justify-between gap-8 px-5 py-16 lg:flex-row lg:items-end lg:px-8"><div><p className="font-mono text-xs font-semibold uppercase tracking-[.18em] text-(--primary-color)">Build a stronger evidence process</p><h2 className="mt-4 max-w-2xl text-4xl font-bold tracking-[-.04em] sm:text-5xl">One platform for the footage you need to trust.</h2></div><a className="inline-flex items-center gap-2 bg-(--primary-color) px-5 py-3 text-sm font-semibold text-(--surface-color) transition-colors hover:bg-(--secondary-color)" href="#workflow">Start with acquisition <ArrowRight aria-hidden="true" className="size-4" /></a></div></section>
      <footer className="overflow-hidden border-t border-(--mechanism-line) bg-(--mechanism-color) text-(--surface-color)">
        <div className="mx-auto max-w-7xl px-5 pb-8 pt-14 lg:px-8">
          <div className="grid gap-10 border-b border-(--mechanism-line) pb-12 md:grid-cols-[1fr_auto_auto] md:gap-20">
            <div><p className="max-w-md text-lg font-semibold">Forensic video evidence, without vendor lock-in.</p><p className="mt-3 max-w-md text-sm leading-7 text-(--muted-text-color)">A unified workspace for defensible acquisition, recovery, analysis, and reporting across DVR and NVR systems.</p></div>
            <div><p className="font-mono text-[10px] uppercase tracking-[.18em] text-(--secondary-color)">Platform</p><div className="mt-4 flex flex-col gap-3 text-sm"><a className="transition-colors hover:text-(--secondary-color)" href="#workflow">Workflow</a><a className="transition-colors hover:text-(--secondary-color)" href="#analysis">Analysis</a><a className="transition-colors hover:text-(--secondary-color)" href="#integrity">Integrity</a></div></div>
            <div><p className="font-mono text-[10px] uppercase tracking-[.18em] text-(--secondary-color)">Evidence</p><div className="mt-4 flex flex-col gap-3 text-sm"><a className="transition-colors hover:text-(--secondary-color)" href="#network">Connected sites</a><a className="transition-colors hover:text-(--secondary-color)" href="#workflow">Chain of custody</a><a className="transition-colors hover:text-(--secondary-color)" href="#integrity">Verification</a></div></div>
          </div>
          <Logo className="my-10 whitespace-nowrap" display inverse />
          <div className="flex flex-col gap-3 border-t border-(--mechanism-line) pt-6 text-xs text-(--muted-text-color) sm:flex-row sm:items-center sm:justify-between"><span>© {new Date().getFullYear()} VigiTrace</span><span className="flex items-center gap-2"><CircleCheck aria-hidden="true" className="size-4 text-(--success-color)" />Evidence-first workflow</span></div>
        </div>
      </footer>
    </main>
  );
}

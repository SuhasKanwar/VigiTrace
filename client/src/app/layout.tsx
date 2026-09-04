import type { Metadata } from "next";
import { ToastProvider } from "@/components/ui/toast";
import "./globals.css";

export const metadata: Metadata = {
  title: "VigiTrace",
  description: "A unified multi-vendor DVR/NVR forensic platform for standardized evidence acquisition, recovery, analysis, and validation. It parses proprietary formats, recovers deleted footage, normalizes timestamps, verifies integrity using hashes, correlates events, and generates forensic reports with AI-based video analytics.",
  authors: [
    { name: "NullPointers", url: "https://github.com/SuhasKanwar/VigiTrace" },
    { name: "Suhas Kanwar", url: "https://suhaskanwar.vercel.app" },
    { name: "Pratyaksh Saluja", url: "https://github.com/PratyakshSaluja" }
  ],
  keywords: [
    "VigiTrace",
    "Forensic Video Analysis",
    "DVR/NVR Evidence Acquisition",
    "Video Recovery",
    "Timestamp Normalization",
    "Integrity Verification",
    "Event Correlation",
    "AI-based Video Analytics",
    "Forensic Report Generation",
    "Multi-vendor Support",
    "Proprietary Format Parsing",
    "Deleted Footage Recovery",
    "Hash-based Integrity Checks",
    "Video Forensics",
    "Digital Evidence Management"
  ]
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      data-scroll-behavior="smooth"
      className={`h-full antialiased`}
    >
      <body className="min-h-full flex flex-col"><ToastProvider>{children}</ToastProvider></body>
    </html>
  );
}

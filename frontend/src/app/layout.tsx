import type { Metadata } from "next";
import { Archivo, IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";
import Navbar from "@/components/Navbar";

// Display: industrial grotesque, used heavy and wide.
const archivo = Archivo({
  variable: "--font-display",
  subsets: ["latin"],
});

// Body: technical neutral for prose.
const plexSans = IBM_Plex_Sans({
  variable: "--font-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

// Data: telemetry, VINs, readouts.
const plexMono = IBM_Plex_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "AUTO·AI — describe the drive",
  description:
    "Semantic car search. Describe what you want in plain words; the fleet reports how closely each vehicle matches.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${archivo.variable} ${plexSans.variable} ${plexMono.variable} h-full`}
    >
      <body className="flex min-h-full flex-col">
        <Navbar />
        <main className="mx-auto w-full max-w-7xl flex-1 px-5 py-8 sm:px-6">
          {children}
        </main>
        <footer className="border-t border-line/70">
          <div className="mx-auto flex max-w-7xl flex-col gap-1 px-5 py-6 font-mono text-[11px] uppercase tracking-widest text-haze sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <span>AUTO·AI — semantic vehicle retrieval</span>
            <span>1,000 vehicles · 768-dim vectors · demo build</span>
          </div>
        </footer>
      </body>
    </html>
  );
}

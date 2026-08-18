import SearchExperience from "@/components/SearchExperience";

const TELEMETRY = [
  "1,000 vehicles",
  "768-dim vectors",
  "20 makes",
  "€17.5k–155k",
];

export default function Home() {
  return (
    <div className="flex flex-col gap-9">
      <section className="pt-4">
        {/* telemetry strip */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px] uppercase tracking-widest text-haze">
          <span className="flex items-center gap-1.5 text-lume">
            <span className="h-1.5 w-1.5 rounded-full bg-go shadow-[0_0_6px_var(--go)]" />
            Fleet online
          </span>
          {TELEMETRY.map((t) => (
            <span key={t} className="flex items-center gap-3 before:text-line before:content-['/']">
              {t}
            </span>
          ))}
        </div>

        <h1 className="mt-5 max-w-3xl font-display text-5xl font-extrabold leading-[0.95] tracking-tight text-lume sm:text-6xl">
          Describe the drive.
        </h1>
        <p className="mt-4 max-w-xl text-lg leading-relaxed text-haze">
          Say what you actually want, in plain words. The system reads meaning
          across all 1,000 vehicles and scores how closely each one matches — no
          dropdown gymnastics.
        </p>
      </section>

      <SearchExperience />
    </div>
  );
}

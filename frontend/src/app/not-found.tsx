import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-5 py-24 text-center">
      <span className="font-mono text-[11px] uppercase tracking-widest text-haze">
        Error 404 · off the map
      </span>
      <h1 className="font-display text-5xl font-extrabold tracking-tight text-lume">
        No route.
      </h1>
      <p className="font-mono text-sm text-haze">
        That page or vehicle isn&apos;t in the fleet.
      </p>
      <div className="flex gap-3">
        <Link
          href="/"
          className="rounded-lg border border-cyan/50 bg-cyan/10 px-5 py-2.5 font-mono text-sm font-semibold uppercase tracking-widest text-cyan transition hover:bg-cyan/20"
        >
          Search
        </Link>
        <Link
          href="/browse"
          className="rounded-lg border border-line px-5 py-2.5 font-mono text-sm uppercase tracking-widest text-haze transition hover:border-cyan/40 hover:text-lume"
        >
          Browse
        </Link>
      </div>
    </div>
  );
}

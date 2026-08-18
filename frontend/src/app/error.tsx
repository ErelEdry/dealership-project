"use client";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-5 py-24 text-center">
      <span className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-widest text-amber">
        <span className="h-1.5 w-1.5 rounded-full bg-amber shadow-[0_0_6px_var(--amber)]" />
        System fault
      </span>
      <h1 className="font-display text-3xl font-extrabold tracking-tight text-lume">
        Signal lost.
      </h1>
      <p className="font-mono text-sm text-haze">
        {error.message || "Something went wrong reaching the fleet."}
        <br />
        Check that the API is running on :8000.
      </p>
      <button
        onClick={reset}
        className="rounded-lg border border-cyan/50 bg-cyan/10 px-5 py-2.5 font-mono text-sm font-semibold uppercase tracking-widest text-cyan transition hover:bg-cyan/20"
      >
        Retry
      </button>
    </div>
  );
}

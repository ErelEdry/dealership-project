"use client";

// Dual-thumb range slider. Two transparent <input type=range> overlaid on a
// shared track; the highlighted segment shows the selected span.
export default function RangeSlider({
  min,
  max,
  step = 1,
  value,
  onChange,
  format,
}: {
  min: number;
  max: number;
  step?: number;
  value: [number, number];
  onChange: (next: [number, number]) => void;
  format: (v: number) => string;
}) {
  const [lo, hi] = value;
  const span = max - min || 1;
  const pct = (v: number) => ((v - min) / span) * 100;

  return (
    <div className="flex flex-col gap-2">
      <div className="relative h-4">
        <div className="absolute top-1/2 h-1 w-full -translate-y-1/2 rounded-full bg-line" />
        <div
          className="absolute top-1/2 h-1 -translate-y-1/2 rounded-full bg-cyan"
          style={{ left: `${pct(lo)}%`, right: `${100 - pct(hi)}%` }}
        />
        <input
          aria-label="Minimum"
          className="hmi-range"
          type="range"
          min={min}
          max={max}
          step={step}
          value={lo}
          onChange={(e) => onChange([Math.min(Number(e.target.value), hi), hi])}
        />
        <input
          aria-label="Maximum"
          className="hmi-range"
          type="range"
          min={min}
          max={max}
          step={step}
          value={hi}
          onChange={(e) => onChange([lo, Math.max(Number(e.target.value), lo)])}
        />
      </div>
      <div className="flex justify-between font-mono text-[11px] text-haze">
        <span>{format(lo)}</span>
        <span>{format(hi)}</span>
      </div>
    </div>
  );
}

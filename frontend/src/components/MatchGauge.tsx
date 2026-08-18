"use client";

import { useEffect, useState } from "react";

/**
 * The signature element: the semantic match (or AI confidence) rendered as an
 * instrument gauge. A 270° cyan arc sweeps up from zero on mount, reading like
 * a charge meter on a dashboard. This is the one bold thing on the page.
 */
export default function MatchGauge({
  value,
  size = 56,
  stroke = 5,
  label,
}: {
  value: number; // 0..1
  size?: number;
  stroke?: number;
  label?: string;
}) {
  const clamped = Math.max(0, Math.min(1, value));
  const [p, setP] = useState(0);

  useEffect(() => {
    const id = requestAnimationFrame(() => setP(clamped));
    return () => cancelAnimationFrame(id);
  }, [clamped]);

  const cx = size / 2;
  const cy = size / 2;
  const r = (size - stroke) / 2 - 1;
  const c = 2 * Math.PI * r;
  const sweep = 0.75; // 270° arc, gap centred at the bottom
  const arcLen = sweep * c;
  const offset = arcLen * (1 - p);
  const pct = Math.round(clamped * 100);

  return (
    <div
      className="relative grid place-items-center"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`${label ? `${label}: ` : ""}${pct} percent`}
    >
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        style={{ transform: `rotate(135deg)` }}
      >
        {/* track */}
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke="var(--line)"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${arcLen} ${c}`}
        />
        {/* progress */}
        <circle
          className="gauge-arc"
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke="var(--cyan)"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${arcLen} ${c}`}
          strokeDashoffset={offset}
          style={{ filter: "drop-shadow(0 0 4px rgba(70,217,230,0.5))" }}
        />
      </svg>
      <span
        className="absolute font-mono font-semibold text-cyan"
        style={{ fontSize: size * 0.28, lineHeight: 1 }}
      >
        {pct}
      </span>
    </div>
  );
}

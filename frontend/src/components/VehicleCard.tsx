import Link from "next/link";
import type { Vehicle } from "@/lib/types";
import {
  formatMileage,
  formatPrice,
  stockTell,
  tileBackground,
  titleCase,
} from "@/lib/format";
import MatchGauge from "./MatchGauge";
import CarSilhouette from "./CarSilhouette";

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded border border-line bg-panel2 px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide text-haze">
      {children}
    </span>
  );
}

export default function VehicleCard({
  vehicle,
  score,
}: {
  vehicle: Vehicle;
  score?: number;
}) {
  const v = vehicle;
  const tell = stockTell(v.stock_status);

  return (
    <Link
      href={`/vehicles/${v.vin}`}
      className="group flex flex-col overflow-hidden rounded-xl border border-line bg-panel transition duration-200 hover:-translate-y-0.5 hover:border-cyan/45 hover:shadow-[0_10px_40px_-12px_rgba(70,217,230,0.25)]"
    >
      {/* instrument tile */}
      <div
        className="relative flex h-36 items-end p-4"
        style={{ background: tileBackground(v.make + v.model) }}
      >
        <CarSilhouette
          bodyType={v.body_type}
          className="pointer-events-none absolute right-2 top-1/2 h-24 w-auto -translate-y-1/2 text-lume/[0.09]"
        />

        {score !== undefined && (
          <div className="absolute left-3 top-3">
            <MatchGauge value={score} size={52} label="Match" />
          </div>
        )}

        <div className="relative">
          <p className="font-mono text-[11px] uppercase tracking-widest text-haze">
            {v.year} · {titleCase(v.fuel_type)}
          </p>
          <p className="font-display text-lg font-bold leading-tight text-lume">
            {v.make} {v.model}
          </p>
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-3 p-4">
        <div className="flex items-center justify-between">
          <p className="font-mono text-xl font-semibold text-amber">
            {formatPrice(v.price)}
          </p>
          <span className="flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wide text-haze">
            <span
              className="h-2 w-2 rounded-full"
              style={{
                background: tell.color,
                boxShadow: `0 0 6px ${tell.color}`,
              }}
            />
            {tell.label}
          </span>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {v.ai_segment && (
            <span className="rounded border border-cyan/30 bg-cyan/10 px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide text-cyan">
              {v.ai_segment}
            </span>
          )}
          <Chip>{formatMileage(v.mileage)}</Chip>
          {v.transmission && <Chip>{titleCase(v.transmission)}</Chip>}
        </div>

        {v.ai_summary && (
          <p className="line-clamp-2 text-sm leading-relaxed text-haze">
            {v.ai_summary}
          </p>
        )}
      </div>
    </Link>
  );
}

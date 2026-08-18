import Link from "next/link";
import { notFound } from "next/navigation";
import { getVehicle } from "@/lib/api";
import {
  formatMileage,
  formatPrice,
  stockTell,
  tileBackground,
  titleCase,
} from "@/lib/format";
import MatchGauge from "@/components/MatchGauge";
import BookTestDrive from "@/components/BookTestDrive";
import CarSilhouette from "@/components/CarSilhouette";

function Spec({
  label,
  value,
}: {
  label: string;
  value?: string | number | null;
}) {
  if (value === null || value === undefined || value === "") return null;
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-line bg-panel px-4 py-3">
      <dt className="font-mono text-[11px] uppercase tracking-widest text-haze">
        {label}
      </dt>
      <dd className="font-mono text-sm text-lume">{value}</dd>
    </div>
  );
}

function SectionHead({ children }: { children: string }) {
  return (
    <h2 className="mb-3 font-mono text-[11px] uppercase tracking-widest text-haze">
      {children}
    </h2>
  );
}

export default async function VehiclePage(props: PageProps<"/vehicles/[vin]">) {
  const { vin } = await props.params;
  const v = await getVehicle(vin);
  if (!v) notFound();

  const tell = stockTell(v.stock_status);

  return (
    <div className="flex flex-col gap-8">
      <Link
        href="/browse"
        className="font-mono text-[11px] uppercase tracking-widest text-haze transition hover:text-cyan"
      >
        ← Inventory
      </Link>

      {/* instrument hero */}
      <div
        className="relative flex h-56 items-end overflow-hidden rounded-2xl border border-line p-8"
        style={{ background: tileBackground(v.make + v.model) }}
      >
        <CarSilhouette
          bodyType={v.body_type}
          className="pointer-events-none absolute right-4 top-1/2 h-40 w-auto -translate-y-1/2 text-lume/[0.07]"
        />
        <div className="relative">
          <p className="font-mono text-[11px] uppercase tracking-widest text-haze">
            {v.year} · {titleCase(v.fuel_type)} · {titleCase(v.body_type)}
          </p>
          <h1 className="mt-1 font-display text-4xl font-extrabold tracking-tight text-lume sm:text-5xl">
            {v.make} {v.model}
          </h1>
        </div>
      </div>

      <div className="grid gap-8 lg:grid-cols-3">
        <div className="flex flex-col gap-8 lg:col-span-2">
          {v.ai_summary && (
            <section>
              <SectionHead>Overview</SectionHead>
              <p className="text-[15px] leading-relaxed text-haze">
                {v.ai_summary}
              </p>
            </section>
          )}

          {v.ai_selling_points.length > 0 && (
            <section>
              <SectionHead>Highlights</SectionHead>
              <ul className="flex flex-col gap-2.5">
                {v.ai_selling_points.map((p, i) => (
                  <li key={i} className="flex gap-3 text-[15px] text-lume">
                    <span aria-hidden className="mt-1 font-mono text-cyan">
                      ▸
                    </span>
                    <span className="text-haze">{p}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section>
            <SectionHead>Specifications</SectionHead>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <Spec label="Year" value={v.year} />
              <Spec label="Mileage" value={formatMileage(v.mileage)} />
              <Spec label="Fuel" value={titleCase(v.fuel_type)} />
              <Spec label="Transmission" value={titleCase(v.transmission)} />
              <Spec label="Body" value={titleCase(v.body_type)} />
              <Spec label="Segment" value={v.ai_segment} />
              <Spec label="Seats" value={v.seats} />
              <Spec label="Doors" value={v.doors} />
              <Spec label="Engine" value={v.engine} />
              <Spec label="Condition" value={titleCase(v.condition)} />
              <Spec label="Exterior" value={titleCase(v.colour_ext)} />
              <Spec label="Interior" value={titleCase(v.colour_int)} />
            </dl>
          </section>

          {v.ai_comparable_models.length > 0 && (
            <section>
              <SectionHead>Also consider</SectionHead>
              <div className="flex flex-wrap gap-2">
                {v.ai_comparable_models.map((m, i) => (
                  <span
                    key={i}
                    className="rounded-md border border-line bg-panel px-3 py-1 font-mono text-sm text-haze"
                  >
                    {m}
                  </span>
                ))}
              </div>
            </section>
          )}
        </div>

        {/* purchase console */}
        <aside className="flex h-fit flex-col gap-5 rounded-xl border border-line bg-panel p-6 lg:sticky lg:top-20">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-2 font-mono text-xs uppercase tracking-widest text-haze">
              <span
                className="h-2 w-2 rounded-full"
                style={{
                  background: tell.color,
                  boxShadow: `0 0 6px ${tell.color}`,
                }}
              />
              {tell.label}
            </span>
            {v.ai_segment && (
              <span className="rounded border border-cyan/30 bg-cyan/10 px-2 py-0.5 font-mono text-[11px] uppercase tracking-wide text-cyan">
                {v.ai_segment}
              </span>
            )}
          </div>

          <p className="font-mono text-4xl font-semibold text-amber">
            {formatPrice(v.price)}
          </p>

          {v.ai_confidence != null && (
            <div className="flex items-center gap-3 border-y border-line py-3">
              <MatchGauge value={v.ai_confidence} size={48} label="AI confidence" />
              <div className="font-mono text-[11px] uppercase leading-relaxed tracking-widest text-haze">
                AI confidence
                <br />
                <span className="text-lume">enrichment score</span>
              </div>
            </div>
          )}

          {v.ai_lifestyle_tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {v.ai_lifestyle_tags.map((t, i) => (
                <span
                  key={i}
                  className="rounded-full border border-line bg-panel2 px-2.5 py-0.5 font-mono text-[11px] uppercase tracking-wide text-haze"
                >
                  {t}
                </span>
              ))}
            </div>
          )}

          <BookTestDrive vin={v.vin} make={v.make} model={v.model} year={v.year} />

          <p className="border-t border-line pt-3 text-center font-mono text-[11px] uppercase tracking-widest text-haze">
            VIN {v.vin}
          </p>
        </aside>
      </div>
    </div>
  );
}

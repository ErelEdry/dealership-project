"use client";

import { useState } from "react";
import { searchVehicles } from "@/lib/api";
import type { SearchResponse } from "@/lib/types";
import VehicleCard from "./VehicleCard";
import { SkeletonGrid } from "./VehicleCardSkeleton";

const PRESETS = [
  "cheap fuel efficient city car for a student",
  "spacious family SUV for road trips",
  "fast electric car with long range",
  "reliable pickup truck for work",
];

export default function SearchExperience() {
  const [query, setQuery] = useState("");
  const [data, setData] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(q: string) {
    const text = q.trim();
    if (!text) return;
    setQuery(text);
    setLoading(true);
    setError(null);
    try {
      const res = await searchVehicles({ query: text, limit: 12 });
      setData(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Search failed");
      setData(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          run(query);
        }}
        className="flex flex-col gap-4"
      >
        {/* command console */}
        <div className="group flex items-center gap-3 rounded-xl border border-line bg-panel px-4 py-3 transition focus-within:border-cyan/60 focus-within:shadow-[0_0_0_3px_rgba(70,217,230,0.12)]">
          <span aria-hidden className="font-mono text-lg text-cyan">
            ⌖
          </span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. cheap electric hatchback for city commuting"
            aria-label="Describe the car you want"
            className="min-w-0 flex-1 bg-transparent font-mono text-base text-lume caret-cyan outline-none placeholder:text-haze/70"
          />
          <button
            type="submit"
            disabled={loading}
            className="shrink-0 rounded-lg border border-cyan/50 bg-cyan/10 px-5 py-2 font-mono text-sm font-semibold uppercase tracking-widest text-cyan transition hover:bg-cyan/20 disabled:opacity-60"
          >
            {loading ? "Reading…" : "Search"}
          </button>
        </div>

        {/* preset routines */}
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[11px] uppercase tracking-widest text-haze">
            Presets
          </span>
          {PRESETS.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => run(ex)}
              className="rounded-full border border-line bg-panel px-3 py-1 text-sm text-haze transition hover:border-cyan/40 hover:text-lume"
            >
              {ex}
            </button>
          ))}
        </div>
      </form>

      {loading && <SkeletonGrid count={8} />}

      {!loading && error && (
        <p className="rounded-lg border border-amber/40 bg-amber/10 px-4 py-3 font-mono text-sm text-amber">
          Signal lost — {error}. Check that the API is running on :8000.
        </p>
      )}

      {!loading &&
        data &&
        (data.count === 0 ? (
          <p className="rounded-lg border border-line bg-panel px-4 py-10 text-center font-mono text-sm uppercase tracking-widest text-haze">
            No vehicles matched “{data.query}”. Try describing it differently.
          </p>
        ) : (
          <div className="flex flex-col gap-4">
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px] uppercase tracking-widest text-haze">
              <span className="text-lume">{data.count} matches</span>
              <span className="text-line">/</span>
              <span className="normal-case tracking-normal text-haze">
                “{data.query}”
              </span>
              {data.cached && (
                <span className="rounded border border-line px-1.5 py-0.5 text-cyan">
                  cached
                </span>
              )}
            </p>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {data.results.map((hit) => (
                <VehicleCard
                  key={hit.vehicle.vin}
                  vehicle={hit.vehicle}
                  score={hit.score}
                />
              ))}
            </div>
          </div>
        ))}
    </div>
  );
}

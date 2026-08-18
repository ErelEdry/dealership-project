"use client";

import { useCallback, useEffect, useState } from "react";
import { getFacets, listVehicles } from "@/lib/api";
import type {
  FacetCount,
  FacetsResponse,
  VehicleFilters,
  VehicleListResponse,
} from "@/lib/types";
import { titleCase } from "@/lib/format";
import VehicleCard from "./VehicleCard";
import { SkeletonGrid } from "./VehicleCardSkeleton";
import RangeSlider from "./RangeSlider";

const PAGE_SIZE = 12;
const SORTS = [
  { value: "year_desc", label: "Newest first" },
  { value: "price_asc", label: "Price: low to high" },
  { value: "price_desc", label: "Price: high to low" },
  { value: "mileage_asc", label: "Lowest mileage" },
];

type Selected = {
  make?: string;
  fuel_type?: string;
  body_type?: string;
  segment?: string;
};

type Range = [number, number];
type Bounds = { price: Range; year: Range };

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

const priceLabel = (v: number) => `€${Math.round(v / 1000)}k`;

export default function BrowseExperience() {
  const [sel, setSel] = useState<Selected>({});
  const [sort, setSort] = useState("year_desc");
  const [page, setPage] = useState(1);
  const [list, setList] = useState<VehicleListResponse | null>(null);
  const [facets, setFacets] = useState<FacetsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  // Range sliders — driven live, applied to the query after a debounce.
  const [bounds, setBounds] = useState<Bounds | null>(null);
  const [priceRange, setPriceRange] = useState<Range | null>(null);
  const [yearRange, setYearRange] = useState<Range | null>(null);
  const debPrice = useDebounced(priceRange, 350);
  const debYear = useDebounced(yearRange, 350);

  const priceActive =
    !!bounds && !!debPrice &&
    (debPrice[0] > bounds.price[0] || debPrice[1] < bounds.price[1]);
  const yearActive =
    !!bounds && !!debYear &&
    (debYear[0] > bounds.year[0] || debYear[1] < bounds.year[1]);

  useEffect(() => {
    const ranged: VehicleFilters = {};
    if (priceActive && debPrice) {
      ranged.min_price = debPrice[0];
      ranged.max_price = debPrice[1];
    }
    if (yearActive && debYear) {
      ranged.min_year = debYear[0];
      ranged.max_year = debYear[1];
    }
    const filters: VehicleFilters = {
      ...sel,
      ...ranged,
      sort,
      page,
      page_size: PAGE_SIZE,
    };
    setLoading(true);
    setError(null);
    let cancelled = false;
    Promise.all([listVehicles(filters), getFacets({ ...sel, ...ranged })])
      .then(([l, f]) => {
        if (cancelled) return;
        setList(l);
        setFacets(f);
        // Seed slider bounds once, from the unfiltered span.
        setBounds((prev) => {
          if (prev) return prev;
          const b: Bounds = {
            price: [f.price_min ?? 0, f.price_max ?? 0],
            year: [f.year_min ?? 0, f.year_max ?? 0],
          };
          setPriceRange(b.price);
          setYearRange(b.year);
          return b;
        });
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Load failed");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sel, sort, page, debPrice, debYear, reloadKey]);

  const toggle = useCallback((dim: keyof Selected, value: string) => {
    setPage(1);
    setSel((prev) => ({
      ...prev,
      [dim]: prev[dim] === value ? undefined : value,
    }));
  }, []);

  const clearAll = () => {
    setSel({});
    setPage(1);
    if (bounds) {
      setPriceRange(bounds.price);
      setYearRange(bounds.year);
    }
  };

  const activeCount =
    Object.values(sel).filter(Boolean).length +
    (priceActive ? 1 : 0) +
    (yearActive ? 1 : 0);
  const totalPages = list ? Math.max(1, Math.ceil(list.total / PAGE_SIZE)) : 1;
  const initialLoading = loading && list === null;

  const group = (
    title: string,
    dim: keyof Selected,
    items: FacetCount[] | undefined,
    cap = 100,
  ) => {
    if (!items?.length) return null;
    return (
      <div className="flex flex-col gap-1.5">
        <h3 className="font-mono text-[11px] uppercase tracking-widest text-haze">
          {title}
        </h3>
        <div className="flex flex-col gap-0.5">
          {items.slice(0, cap).map((f) => {
            const active = sel[dim] === f.value;
            return (
              <button
                key={f.value}
                onClick={() => toggle(dim, f.value)}
                className={`flex items-center justify-between gap-2 rounded-md border-l-2 px-3 py-1.5 text-left text-sm transition ${
                  active
                    ? "border-cyan bg-cyan/10 text-lume"
                    : "border-transparent text-haze hover:bg-panel hover:text-lume"
                }`}
              >
                <span>{titleCase(f.value)}</span>
                <span
                  className={`font-mono text-[11px] ${
                    active ? "text-cyan" : "text-haze/70"
                  }`}
                >
                  {f.count}
                </span>
              </button>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      {/* control panel */}
      <aside className="flex h-fit w-full shrink-0 flex-col gap-5 rounded-xl border border-line bg-panel/60 p-5 lg:sticky lg:top-20 lg:w-64">
        <div className="flex items-center justify-between border-b border-line pb-3">
          <h2 className="font-mono text-xs uppercase tracking-widest text-lume">
            Filters
          </h2>
          {activeCount > 0 && (
            <button
              onClick={clearAll}
              className="font-mono text-[11px] uppercase tracking-wide text-cyan hover:underline"
            >
              Clear ({activeCount})
            </button>
          )}
        </div>

        {bounds && priceRange && bounds.price[0] < bounds.price[1] && (
          <div className="flex flex-col gap-2">
            <h3 className="font-mono text-[11px] uppercase tracking-widest text-haze">
              Price
            </h3>
            <RangeSlider
              min={bounds.price[0]}
              max={bounds.price[1]}
              step={250}
              value={priceRange}
              onChange={(r) => {
                setPage(1);
                setPriceRange(r);
              }}
              format={priceLabel}
            />
          </div>
        )}

        {bounds && yearRange && bounds.year[0] < bounds.year[1] && (
          <div className="flex flex-col gap-2">
            <h3 className="font-mono text-[11px] uppercase tracking-widest text-haze">
              Year
            </h3>
            <RangeSlider
              min={bounds.year[0]}
              max={bounds.year[1]}
              step={1}
              value={yearRange}
              onChange={(r) => {
                setPage(1);
                setYearRange(r);
              }}
              format={String}
            />
          </div>
        )}

        {group("Fuel", "fuel_type", facets?.fuel_type)}
        {group("Body", "body_type", facets?.body_type)}
        {group("Segment", "segment", facets?.ai_segment, 8)}
        {group("Make", "make", facets?.make, 10)}
      </aside>

      {/* results */}
      <section className="flex-1">
        <div className="mb-4 flex items-center justify-between gap-3">
          <p className="font-mono text-[11px] uppercase tracking-widest text-haze">
            {list ? (
              <>
                <span className="text-lume">
                  {list.total.toLocaleString()}
                </span>{" "}
                vehicles
              </>
            ) : (
              "Loading…"
            )}
          </p>
          <label className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-widest text-haze">
            Sort
            <select
              value={sort}
              onChange={(e) => {
                setSort(e.target.value);
                setPage(1);
              }}
              className="rounded-md border border-line bg-panel px-3 py-1.5 font-sans text-sm normal-case tracking-normal text-lume outline-none focus:border-cyan/60"
            >
              {SORTS.map((s) => (
                <option key={s.value} value={s.value} className="bg-panel">
                  {s.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        {error ? (
          <div className="flex flex-col items-center gap-4 rounded-lg border border-amber/40 bg-amber/5 px-4 py-16 text-center">
            <p className="font-mono text-sm text-amber">
              Signal lost — {error}.
            </p>
            <button
              onClick={() => setReloadKey((k) => k + 1)}
              className="rounded-md border border-cyan/50 bg-cyan/10 px-4 py-2 font-mono text-xs font-semibold uppercase tracking-widest text-cyan transition hover:bg-cyan/20"
            >
              Retry
            </button>
          </div>
        ) : initialLoading ? (
          <SkeletonGrid
            count={9}
            className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3"
          />
        ) : (
          <>
            <div
              className={`grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3 ${
                loading ? "opacity-40" : ""
              }`}
            >
              {list?.results.map((v) => (
                <VehicleCard key={v.vin} vehicle={v} />
              ))}
            </div>

            {list && list.total === 0 && (
              <p className="rounded-lg border border-line bg-panel px-4 py-16 text-center font-mono text-sm uppercase tracking-widest text-haze">
                No vehicles match these filters.
              </p>
            )}

            {list && list.total > PAGE_SIZE && (
              <div className="mt-8 flex items-center justify-center gap-4 font-mono text-xs uppercase tracking-widest">
                <button
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                  className="rounded-md border border-line px-4 py-2 text-haze transition hover:border-cyan/40 hover:text-lume disabled:opacity-30 disabled:hover:border-line disabled:hover:text-haze"
                >
                  Prev
                </button>
                <span className="text-haze">
                  <span className="text-lume">{page}</span> / {totalPages}
                </span>
                <button
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                  className="rounded-md border border-line px-4 py-2 text-haze transition hover:border-cyan/40 hover:text-lume disabled:opacity-30 disabled:hover:border-line disabled:hover:text-haze"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}

// Placeholder tile matching VehicleCard's shape while results load.
export default function VehicleCardSkeleton() {
  return (
    <div className="flex flex-col overflow-hidden rounded-xl border border-line bg-panel">
      <div className="hmi-skeleton h-36 bg-panel2" />
      <div className="flex flex-col gap-3 p-4">
        <div className="flex items-center justify-between">
          <div className="hmi-skeleton h-6 w-24 rounded bg-panel2" />
          <div className="hmi-skeleton h-4 w-16 rounded bg-panel2" />
        </div>
        <div className="flex gap-1.5">
          <div className="hmi-skeleton h-5 w-20 rounded bg-panel2" />
          <div className="hmi-skeleton h-5 w-14 rounded bg-panel2" />
        </div>
        <div className="hmi-skeleton h-4 w-full rounded bg-panel2" />
        <div className="hmi-skeleton h-4 w-2/3 rounded bg-panel2" />
      </div>
    </div>
  );
}

export function SkeletonGrid({
  count = 8,
  className = "grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4",
}: {
  count?: number;
  className?: string;
}) {
  return (
    <div className={className} aria-hidden>
      {Array.from({ length: count }).map((_, i) => (
        <VehicleCardSkeleton key={i} />
      ))}
    </div>
  );
}

import type { Metadata } from "next";
import BrowseExperience from "@/components/BrowseExperience";

export const metadata: Metadata = { title: "Browse — AUTO·AI" };

export default function BrowsePage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="font-mono text-[11px] uppercase tracking-widest text-haze">
          Inventory
        </p>
        <h1 className="mt-1 font-display text-3xl font-extrabold tracking-tight text-lume">
          The full fleet
        </h1>
      </div>
      <BrowseExperience />
    </div>
  );
}

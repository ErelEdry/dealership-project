const eur = new Intl.NumberFormat("en-IE", {
  style: "currency",
  currency: "EUR",
  maximumFractionDigits: 0,
});

const num = new Intl.NumberFormat("en-US");

export const formatPrice = (n: number) => eur.format(n);
export const formatMileage = (n: number) => `${num.format(n)} km`;

export const titleCase = (s?: string | null) =>
  s ? s.replace(/\b\w/g, (c) => c.toUpperCase()) : "";

// Deterministic hash → stable "backlight" hue per make, so each instrument
// tile has its own faint tint without the old rainbow gradients.
function hash(key: string): number {
  let h = 0;
  for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) >>> 0;
  return h;
}

export function hueFor(key: string): number {
  return hash(key) % 360;
}

// A dark instrument-tile background with a single faint hue glow, used behind
// the make monogram. Returns a CSS `background` value.
export function tileBackground(key: string): string {
  const hue = hueFor(key);
  return (
    `radial-gradient(120% 120% at 78% 18%, hsl(${hue} 60% 22% / 0.55), transparent 60%),` +
    `radial-gradient(90% 90% at 12% 96%, hsl(${(hue + 40) % 360} 55% 20% / 0.35), transparent 55%),` +
    `linear-gradient(160deg, #141b23, #0c1116)`
  );
}

// Dashboard tell-tale lights: green = go, amber = caution, dim = off, blue = service.
type Tell = { color: string; label: string };

const STOCK: Record<string, Tell> = {
  available: { color: "var(--go)", label: "In stock" },
  reserved: { color: "var(--amber)", label: "Reserved" },
  sold: { color: "var(--haze)", label: "Sold" },
  workshop: { color: "var(--info)", label: "In workshop" },
};

export const stockTell = (s: string): Tell =>
  STOCK[s] ?? { color: "var(--haze)", label: titleCase(s) };

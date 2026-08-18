import type {
  BookingRequest,
  BookingResponse,
  FacetsResponse,
  SearchRequest,
  SearchResponse,
  Vehicle,
  VehicleFilters,
  VehicleListResponse,
} from "./types";

// The browser reaches the API at its host-published URL; server-rendered code
// (the detail page) runs inside the container and must use the internal service
// name. `typeof window` picks the right base for each execution context. Both
// fall back to the public URL, so `npm run dev` on the host still works.
const CLIENT_API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const SERVER_API = process.env.API_URL_INTERNAL ?? CLIENT_API;

export const API_URL = typeof window === "undefined" ? SERVER_API : CLIENT_API;

function qs(params: object): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export async function searchVehicles(
  body: SearchRequest,
): Promise<SearchResponse> {
  const res = await fetch(`${API_URL}/api/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Search failed (${res.status})`);
  return res.json();
}

export async function listVehicles(
  filters: VehicleFilters = {},
): Promise<VehicleListResponse> {
  const res = await fetch(`${API_URL}/api/vehicles${qs(filters)}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`List failed (${res.status})`);
  return res.json();
}

export async function getFacets(
  filters: VehicleFilters = {},
): Promise<FacetsResponse> {
  const res = await fetch(`${API_URL}/api/vehicles/facets${qs(filters)}`, {
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`Facets failed (${res.status})`);
  return res.json();
}

export async function createBooking(
  body: BookingRequest,
): Promise<BookingResponse> {
  const res = await fetch(`${API_URL}/api/bookings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    // Surface the API's own message (409 slot taken, 404 VIN, 422 validation).
    let message = `Booking failed (${res.status})`;
    try {
      const data = await res.json();
      if (typeof data.detail === "string") message = data.detail;
      else if (Array.isArray(data.detail) && data.detail[0]?.msg)
        message = data.detail[0].msg;
    } catch {
      /* non-JSON error body — keep the generic message */
    }
    throw new Error(message);
  }
  return res.json();
}

export async function getVehicle(vin: string): Promise<Vehicle | null> {
  const res = await fetch(`${API_URL}/api/vehicles/${vin}`, {
    cache: "no-store",
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Detail failed (${res.status})`);
  return res.json();
}

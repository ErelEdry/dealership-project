// Mirrors the FastAPI Phase 3 schemas (app/schemas/search.py).

export interface Vehicle {
  vin: string;
  dealer_id?: string | null;
  stock_id?: string | null;
  make: string;
  model: string;
  year: number;
  trim?: string | null;
  body_type?: string | null;
  fuel_type?: string | null;
  transmission?: string | null;
  engine?: string | null;
  seats?: number | null;
  doors?: number | null;
  mileage: number;
  price: number;
  condition?: string | null;
  colour_ext?: string | null;
  colour_int?: string | null;
  features: string[];
  images: string[];
  stock_status: string;
  ai_lifestyle_tags: string[];
  ai_segment?: string | null;
  ai_summary?: string | null;
  ai_selling_points: string[];
  ai_comparable_models: string[];
  ai_confidence?: number | null;
  needs_review?: boolean | null;
}

export interface SearchHit {
  score: number;
  vehicle: Vehicle;
}

export interface SearchResponse {
  query: string;
  count: number;
  cached: boolean;
  results: SearchHit[];
}

export interface VehicleListResponse {
  total: number;
  page: number;
  page_size: number;
  results: Vehicle[];
}

export interface FacetCount {
  value: string;
  count: number;
}

export interface FacetsResponse {
  total: number;
  make: FacetCount[];
  fuel_type: FacetCount[];
  body_type: FacetCount[];
  ai_segment: FacetCount[];
  stock_status: FacetCount[];
  price_min: number | null;
  price_max: number | null;
  year_min: number | null;
  year_max: number | null;
}

export interface SearchRequest {
  query: string;
  limit?: number;
  make?: string;
  fuel_type?: string;
  body_type?: string;
  segment?: string;
  min_price?: number;
  max_price?: number;
  min_year?: number;
  max_year?: number;
  seats?: number;
  stock_status?: string;
  rerank?: boolean;
}

export interface BookingRequest {
  vehicle_vin: string;
  customer_name: string;
  customer_email: string;
  customer_phone: string;
  appointment_datetime: string; // ISO, naive local e.g. "2026-09-01T14:00"
  notes?: string;
}

export interface BookingResponse {
  id: string;
  vehicle_vin: string;
  customer_name: string;
  appointment_datetime: string;
  status: string;
  created_at: string;
}

export interface VehicleFilters {
  page?: number;
  page_size?: number;
  make?: string;
  fuel_type?: string;
  body_type?: string;
  segment?: string;
  min_price?: number;
  max_price?: number;
  min_year?: number;
  max_year?: number;
  stock_status?: string;
  sort?: string;
}

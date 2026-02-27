import type { FeatureCollection, Geometry } from 'geojson';

export interface CompoundAlertProperties {
  id?: string;
  score?: number;
  title?: string;
  name?: string;
  summary?: string;
  explanation?: string;
  driver?: string;
  impact?: string;
  recommendation?: string;
  [key: string]: unknown;
}

const COMPOUND_API_URL = import.meta.env.VITE_COMPOUND_API_URL as string | undefined;

export interface CompoundSystemStatus {
  provider_status: Array<{
    provider: string;
    last_success_at: string | null;
    last_error_at: string | null;
    last_error?: string | null;
    consecutive_failures: number;
    circuit_open_until: string | null;
  }>;
  events_freshness: string | null;
  hazards_freshness: string | null;
  alerts_freshness: string | null;
}

async function call(path: string, init?: RequestInit): Promise<Response> {
  if (!COMPOUND_API_URL) throw new Error('VITE_COMPOUND_API_URL is not configured.');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    return await fetch(`${COMPOUND_API_URL}${path}`, { ...init, signal: controller.signal, headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) } });
  } finally {
    clearTimeout(timer);
  }
}

async function fetchGeoJson(path: string, timestep: number): Promise<FeatureCollection<Geometry, CompoundAlertProperties>> {
  const response = await call(`${path}?run_id=latest&timestep=${Math.max(0, Math.floor(timestep))}`);
  if (!response.ok) throw new Error(`Compound API request failed: ${response.status}`);
  return response.json();
}

export function fetchCompoundHazards(timestep: number) {
  return fetchGeoJson('/compound/hazards', timestep);
}

export function fetchCompoundAlerts(timestep: number) {
  return fetchGeoJson('/compound/alerts', timestep);
}

export async function refreshCompoundHazards(
  bbox: [number, number, number, number],
  runId: string = 'latest',
  timestepHours: number[] = [0, 6, 12, 24],
  hazardTypes: string[] = ['WIND', 'RAIN', 'HEAT'],
) {
  const response = await call('/compound/hazards/generate', {
    method: 'POST',
    body: JSON.stringify({ run_id: runId, bbox, timestep_hours: timestepHours, hazard_types: hazardTypes }),
  });
  if (!response.ok) throw new Error(`Hazard generation failed: ${response.status}`);
  return response.json();
}

export async function fetchCompoundSystemStatus(): Promise<CompoundSystemStatus> {
  const response = await call('/system/status');
  if (!response.ok) throw new Error(`System status request failed: ${response.status}`);
  return response.json();
}

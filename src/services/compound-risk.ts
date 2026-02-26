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

export async function refreshCompoundHazards(bbox: [number, number, number, number], runId: string = 'latest') {
  const response = await call('/compound/hazards/generate', {
    method: 'POST',
    body: JSON.stringify({ run_id: runId, bbox, timestep_hours: [0, 6, 12, 24], hazard_types: ['WIND', 'RAIN', 'HEAT'] }),
  });
  if (!response.ok) throw new Error(`Hazard generation failed: ${response.status}`);
  return response.json();
}

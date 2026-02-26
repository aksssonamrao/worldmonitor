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

async function fetchGeoJson(path: string, timestep: number): Promise<FeatureCollection<Geometry, CompoundAlertProperties>> {
  if (!COMPOUND_API_URL) {
    throw new Error(
      'VITE_COMPOUND_API_URL is not configured. Please set the VITE_COMPOUND_API_URL environment variable (e.g., in your .env file or deployment configuration) before building or running this application.'
    );
  }

  const ts = Math.max(0, Math.min(2, Math.floor(timestep)));
  const url = `${COMPOUND_API_URL}${path}?timestep=${ts}`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Compound API request failed: ${response.status}`);
  }
  return response.json();
}

export function fetchCompoundHazards(timestep: number) {
  return fetchGeoJson('/compound/hazards', timestep);
}

export function fetchCompoundAlerts(timestep: number) {
  return fetchGeoJson('/compound/alerts', timestep);
}

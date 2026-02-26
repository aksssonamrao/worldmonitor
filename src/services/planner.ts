export interface PlannerStop {
  type: 'depot' | 'job';
  id: string;
  lat: number;
  lon: number;
  eta_min?: number;
}

export interface PlannerRoute {
  vehicle_id: string;
  stops: PlannerStop[];
  distance_km: number;
  time_min: number;
  risk_cost: number;
}

export interface PlannerResponse {
  plan_id: string;
  objective: { total_cost: number; distance_km: number; time_min: number; risk_cost: number };
  routes: PlannerRoute[];
  constraints_ok: boolean;
  explain: { high_level: string; tradeoffs: string[]; assumptions: string[] };
  llm_summary: string | null;
}

const PLANNER_API_URL = import.meta.env.VITE_PLANNER_API_URL as string | undefined;

const DEMO_CASE = {
  vehicles: [
    { id: 'v1', start_depot_id: 'd1', capacity: 8, max_route_time_min: 260 },
    { id: 'v2', start_depot_id: 'd1', capacity: 8, max_route_time_min: 260 },
  ],
  depots: [{ id: 'd1', lat: 37.74, lon: -122.58 }],
  jobs: [
    { id: 'j1', lat: 37.76, lon: -122.55, demand: 2, service_time_min: 8, time_window: [0, 480] },
    { id: 'j2', lat: 37.78, lon: -122.53, demand: 1, service_time_min: 8, time_window: [0, 480] },
    { id: 'j3', lat: 37.79, lon: -122.5, demand: 2, service_time_min: 8, time_window: [0, 480] },
    { id: 'j4', lat: 37.77, lon: -122.47, demand: 1, service_time_min: 8, time_window: [0, 480] },
    { id: 'j5', lat: 37.75, lon: -122.43, demand: 2, service_time_min: 8, time_window: [0, 480] },
    { id: 'j6', lat: 37.73, lon: -122.41, demand: 2, service_time_min: 8, time_window: [0, 480] },
    { id: 'j7', lat: 37.71, lon: -122.45, demand: 2, service_time_min: 8, time_window: [0, 480] },
    { id: 'j8', lat: 37.72, lon: -122.5, demand: 2, service_time_min: 8, time_window: [0, 480] },
  ],
};

const PLANNER_REQUEST_TIMEOUT_MS = 10_000;

export async function generatePlannerPlan(alertId: string, runId: string, timestep: number): Promise<PlannerResponse> {
  if (!PLANNER_API_URL) {
    throw new Error('VITE_PLANNER_API_URL is not configured.');
  }

  const payload = {
    run_id: runId,
    timestep,
    alert_id: alertId,
    ...DEMO_CASE,
    objective_weights: { distance: 1.0, time: 0.2, risk: 3.0 },
    risk_model: { mode: 'polygon_intersection', sample_points_per_leg: 10 },
  };

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), PLANNER_REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(`${PLANNER_API_URL}/plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(`Planner request failed (${response.status})`);
    }
    return response.json() as Promise<PlannerResponse>;
  } finally {
    clearTimeout(timeoutId);
  }
}

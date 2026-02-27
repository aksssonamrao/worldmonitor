import maplibregl, { LngLatBoundsLike, Map as MaplibreMap, Popup } from 'maplibre-gl';
import { getTopContainerPorts } from './config/ports';

type Coord = [number, number];
type LineStringGeometry = { type: 'LineString'; coordinates: Coord[] };
type RouteOption = {
  id: string;
  name: 'Fastest' | 'Balanced' | 'Safest';
  geometry: LineStringGeometry;
  distance_km: number;
  eta_hours: number;
  summary_risk: { total: number; weather: number; news: number; compound: number };
};
type FeatureCollection = { type: 'FeatureCollection'; features: Array<any> };

type Mode = 'default' | 'fallback' | 'multi-stop';

type RouteScore = {
  total_risk: number;
  segment_scores: Array<{ segment_index: number; score: number; geometry: { type: 'LineString'; coordinates: Coord[] } }>;
  top_evidence: { events: Array<any>; alerts: Array<any>; hazards: Array<any> };
};

type MitigationOption = {
  option_id: string;
  label: string;
  geometry: LineStringGeometry;
  eta_hours: number;
  delta_eta_hours: number;
  risk_total: number;
  delta_risk: number;
  evidence: { incidents: Array<any>; hazards: Array<any>; alerts: Array<any> };
  citations: string[];
};

type MitigationResponse = {
  baseline: { eta_hours: number; risk_total: number };
  options: MitigationOption[];
  recommended_option_id: string;
  robustness: { win_rate: Array<{ option_id: string; win_pct: number }> };
};

export class App {
  private container: HTMLElement;
  private map!: MaplibreMap;
  private popup = new Popup({ closeButton: false, closeOnClick: false });
  private routes: RouteOption[] = [];
  private selectedRouteId: string | null = null;
  private scoreByRoute = new globalThis.Map<string, RouteScore>();
  private mode: Mode = 'default';
  private mitigation: MitigationResponse | null = null;
  private selectedAoiId: string | null = null;
  private aoiGeometries = new globalThis.Map<string, any>();

  constructor(containerId: string) {
    const container = document.getElementById(containerId);
    if (!container) throw new Error(`Missing app container: ${containerId}`);
    this.container = container;
  }

  async init(): Promise<void> {
    this.container.innerHTML = `<main class="app-shell">
      <div id="map"></div>
      <aside class="panel panel-left">
        <h3>Shipment Builder</h3>
        <p id="status" style="margin:0;font-size:12px;opacity:.85"></p>
        <label>Origin (lat,lon)<input id="origin" value="37.7749,-122.4194"></label>
        <label>Destination (lat,lon)<input id="destination" value="34.0522,-118.2437"></label>
        <label>Depart time<input id="depart" type="datetime-local"></label>
        <label>Arrive by<input id="arrive" type="datetime-local"></label>
        <label>Risk appetite <input id="risk" type="range" min="0" max="1" step="0.1" value="0.5"></label>
        <button id="generate">Generate Options</button>
        <button id="mitigate">Mitigate</button>
        <label>Mode<select id="mode"><option value="default">Default</option><option value="fallback">Fallback</option><option value="multi-stop">Multi-stop</option></select></label>
        <label>Stops (lat,lon per line)<textarea id="stops" rows="4" placeholder="36.0,-120.0"></textarea></label>
      </aside>
      <aside class="panel panel-right"><h3>Route Options</h3><div id="route-cards"></div><div id="mitigation-panel"></div><h4>Issues along route</h4><div id="issues"></div><hr><h3>Watchlists</h3><label>Name<input id="aoi-name" value="Primary AOI"></label><label>Radius km<input id="aoi-radius" value="80"></label><button id="aoi-create">Create AOI from map center</button><button id="aoi-snapshot">Manual Snapshot</button><button id="aoi-memo">Generate memo</button><div id="aoi-list"></div><h4>Changes</h4><div id="aoi-changes"></div></aside>
      <section class="drawer"><h3>Evidence</h3><div id="evidence"></div></section>
      <div class="legend">Risk 0..100<div class="gradient"></div></div>
    </main>`;

    const now = new Date();
    const in8h = new Date(now.getTime() + 8 * 3600 * 1000);
    (this.container.querySelector('#depart') as HTMLInputElement).value = now.toISOString().slice(0, 16);
    (this.container.querySelector('#arrive') as HTMLInputElement).value = in8h.toISOString().slice(0, 16);

    this.map = new maplibregl.Map({
      container: this.container.querySelector('#map') as HTMLElement,
      style: 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json',
      center: [-120, 36],
      zoom: 4,
    });
    this.map.addControl(new maplibregl.NavigationControl(), 'top-right');
    this.map.on('load', async () => {
      await this.loadEvidenceLayers();
      this.bindUI();
      await this.refreshWatchlists();
    });
  }

  private setStatus(message: string): void {
    const status = this.container.querySelector('#status');
    if (status) status.textContent = message;
  }

  private safeHttpUrl(input: unknown): string | null {
    if (typeof input !== 'string') return null;
    try {
      const parsed = new URL(input);
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') return parsed.toString();
    } catch {
      return null;
    }
    return null;
  }

  private createPopupNode(lines: string[], sourceUrl?: unknown): HTMLElement {
    const container = document.createElement('div');
    for (const line of lines) {
      const row = document.createElement('div');
      row.textContent = line;
      container.appendChild(row);
    }
    const safeUrl = this.safeHttpUrl(sourceUrl);
    if (safeUrl) {
      const link = document.createElement('a');
      link.href = safeUrl;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = 'source↗';
      container.appendChild(link);
    }
    return container;
  }


  private getRoutingApiBase(): string {
    return (import.meta.env.VITE_ROUTING_API_URL || 'http://localhost:8093').replace(/\/$/, '');
  }

  private isValidMode(value: string): value is Mode {
    return value === 'default' || value === 'fallback' || value === 'multi-stop';
  }

  private bindUI(): void {
    this.container.querySelector('#mode')?.addEventListener('change', (event) => {
      const value = (event.target as HTMLSelectElement).value;
      if (!this.isValidMode(value)) {
        this.setStatus('Invalid mode selected; reverting to default');
        this.mode = 'default';
      } else {
        this.mode = value;
      }
      if (this.selectedRouteId) this.selectRoute(this.selectedRouteId, false);
    });
    this.container.querySelector('#generate')?.addEventListener('click', () => {
      this.generateRoutes().catch((error: unknown) => {
        this.setStatus(error instanceof Error ? error.message : 'Failed to generate routes');
      });
    });
    this.container.querySelector('#mitigate')?.addEventListener('click', () => {
      this.runMitigation().catch((error: unknown) => this.setStatus(error instanceof Error ? error.message : 'Mitigation failed'));
    });

    this.container.querySelector('#aoi-create')?.addEventListener('click', () => this.createAoiFromCenter().catch(console.error));
    this.container.querySelector('#aoi-snapshot')?.addEventListener('click', () => this.createSnapshot().catch(console.error));
    this.container.querySelector('#aoi-memo')?.addEventListener('click', () => this.generateMemo().catch(console.error));
  }

  private parsePoint(input: string): { lat: number; lon: number } {
    const parts = input.split(',').map((part) => part.trim());
    if (parts.length !== 2) throw new Error('Coordinates must be in "lat,lon" format');
    const lat = Number(parts[0]);
    const lon = Number(parts[1]);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) throw new Error('Coordinates must be valid numbers');
    return { lat, lon };
  }

  private parseDateInput(input: string, fieldName: string): string {
    const date = new Date(input);
    if (!Number.isFinite(date.getTime())) {
      throw new Error(`${fieldName} is invalid`);
    }
    return date.toISOString();
  }

  private async safeFetchJson<T>(url: string, init?: RequestInit): Promise<T | null> {
    try {
      const response = await fetch(url, init);
      if (!response.ok) {
        this.setStatus(`Request failed (${response.status}) for ${new URL(url).pathname}`);
        return null;
      }
      return (await response.json()) as T;
    } catch (error) {
      console.error('Network error', { url, error });
      this.setStatus('Network error while fetching map data');
      return null;
    }
  }

  private async generateRoutes(): Promise<void> {
    this.setStatus('Generating route options...');
    const origin = this.parsePoint((this.container.querySelector('#origin') as HTMLInputElement).value);
    const destination = this.parsePoint((this.container.querySelector('#destination') as HTMLInputElement).value);
    const depart = this.parseDateInput((this.container.querySelector('#depart') as HTMLInputElement).value, 'Depart time');
    const arrive = this.parseDateInput((this.container.querySelector('#arrive') as HTMLInputElement).value, 'Arrive by');
    const risk = Number((this.container.querySelector('#risk') as HTMLInputElement).value);
    const api = this.getCompoundApiBase();
    const payload = { origin, destination, depart_time: depart, arrive_by: arrive, risk_appetite: risk };

    const options = await this.safeFetchJson<{ routes: RouteOption[] }>(`${api}/routes/options`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!options?.routes?.length) {
      this.setStatus('No routes returned');
      return;
    }

    this.routes = options.routes;
    this.scoreByRoute.clear();
    for (const route of this.routes) {
      const score = await this.safeFetchJson<RouteScore>(`${api}/routes/score`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ geometry: route.geometry, depart_time: depart, arrive_by: arrive }),
      });
      if (score) this.scoreByRoute.set(route.id, score);
    }

    this.mitigation = null;
    this.renderRouteCards();
    this.renderMitigationPanel();
    this.renderRoutesLayer();
    this.setStatus('Route options loaded');
  }

  private renderRouteCards(): void {
    const cards = this.container.querySelector('#route-cards') as HTMLElement;
    cards.replaceChildren();

    for (const route of this.routes) {
      const el = document.createElement('button');
      el.className = `route-card ${this.selectedRouteId === route.id ? 'selected' : ''}`;

      const title = document.createElement('strong');
      title.textContent = route.name;
      const distance = document.createElement('span');
      distance.textContent = `${route.distance_km.toFixed(1)} km · ${route.eta_hours.toFixed(1)}h`;
      const risk = document.createElement('span');
      risk.textContent = `Risk ${route.summary_risk.total.toFixed(1)}`;

      el.append(title, distance, risk);
      el.addEventListener('click', () => this.selectRoute(route.id, true));
      cards.appendChild(el);
    }
  }

  private renderRoutesLayer(): void {
    const features = this.routes.map((route) => ({ type: 'Feature', geometry: route.geometry, properties: { ...route } }));
    const fc = { type: 'FeatureCollection', features } as FeatureCollection;

    if (this.map.getSource('routes')) {
      (this.map.getSource('routes') as maplibregl.GeoJSONSource).setData(fc as any);
    } else {
      this.map.addSource('routes', { type: 'geojson', data: fc as any });
      this.map.addLayer({
        id: 'routes-line',
        type: 'line',
        source: 'routes',
        paint: {
          'line-color': ['match', ['get', 'name'], 'Fastest', '#a8dadc', 'Balanced', '#f4a261', '#2a9d8f'],
          'line-width': ['case', ['==', ['get', 'id'], this.selectedRouteId || ''], 6, 3],
          'line-opacity': ['case', ['==', ['get', 'id'], this.selectedRouteId || ''], 1, 0.4],
          'line-dasharray': ['match', ['get', 'name'], 'Fastest', ['literal', [1, 0]], 'Balanced', ['literal', [2, 1]], ['literal', [0.5, 1.5]]],
        },
        layout: { 'line-cap': 'round', 'line-join': 'round' },
      });

      this.map.on('mousemove', 'routes-line', (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const props = f.properties as any;
        this.popup
          .setLngLat(e.lngLat)
          .setDOMContent(
            this.createPopupNode([
              String(props.name),
              `${Number(props.distance_km).toFixed(1)} km`,
              `ETA ${Number(props.eta_hours).toFixed(1)}h`,
              `Risk ${Number(props.summary_risk?.total ?? 0).toFixed(1)}`,
            ]),
          )
          .addTo(this.map);
      });
      this.map.on('mouseleave', 'routes-line', () => this.popup.remove());
      this.map.on('click', 'routes-line', (e) => {
        const id = String((e.features?.[0]?.properties as any)?.id || '');
        if (id) this.selectRoute(id, true);
      });
    }

    if (!this.selectedRouteId && this.routes[0]) this.selectRoute(this.routes[0].id, false);
  }

  private selectRoute(routeId: string, fly: boolean): void {
    this.selectedRouteId = routeId;
    this.renderRouteCards();
    this.map.setPaintProperty('routes-line', 'line-width', ['case', ['==', ['get', 'id'], routeId], 7, 3]);
    this.map.setPaintProperty('routes-line', 'line-opacity', ['case', ['==', ['get', 'id'], routeId], 1, 0.2]);

    const route = this.routes.find((r) => r.id === routeId);
    if (!route) return;

    if (fly) {
      const bounds = route.geometry.coordinates.reduce(
        (b, c) => b.extend(c),
        new maplibregl.LngLatBounds(route.geometry.coordinates[0], route.geometry.coordinates[0]),
      );
      this.map.fitBounds(bounds as LngLatBoundsLike, { padding: 120, duration: 700 });
    }

    this.renderGradient(routeId);
    this.renderIssues(routeId);
    if (this.mode === 'fallback') this.renderFallback(route).catch(console.error);
    if (this.mode === 'multi-stop') this.renderMultiStop(route).catch(console.error);
  }

  private renderGradient(routeId: string): void {
    const scored = this.scoreByRoute.get(routeId);
    if (!scored) return;

    const features = scored.segment_scores.map((s) => ({ type: 'Feature', geometry: s.geometry, properties: { score: s.score } }));
    const fc = { type: 'FeatureCollection', features } as FeatureCollection;

    if (this.map.getSource('selected-gradient')) {
      (this.map.getSource('selected-gradient') as maplibregl.GeoJSONSource).setData(fc as any);
    } else {
      this.map.addSource('selected-gradient', { type: 'geojson', data: fc as any });
      this.map.addLayer({
        id: 'selected-gradient-line',
        type: 'line',
        source: 'selected-gradient',
        paint: {
          'line-width': 8,
          'line-color': ['interpolate', ['linear'], ['get', 'score'], 0, '#2dc937', 50, '#e7b416', 100, '#cc3232'],
          'line-opacity': 0.95,
        },
      });
    }

    const evidence = this.container.querySelector('#evidence') as HTMLElement;
    evidence.replaceChildren();

    const sections: Array<[string, Array<any>]> = [
      ['Events', scored.top_evidence.events || []],
      ['Alerts', scored.top_evidence.alerts || []],
      ['Hazards', scored.top_evidence.hazards || []],
    ];

    for (const [title, items] of sections) {
      const section = document.createElement('div');
      const heading = document.createElement('strong');
      heading.textContent = title;
      section.appendChild(heading);
      const list = document.createElement('ul');
      for (const item of items.slice(0, 8)) {
        const li = document.createElement('li');
        li.textContent = String(item.title || item.type || item.hazard_type || 'Unknown');
        list.appendChild(li);
      }
      section.appendChild(list);
      evidence.appendChild(section);
    }
  }

  private renderIssues(routeId: string): void {
    const scored = this.scoreByRoute.get(routeId);
    const issues = this.container.querySelector('#issues') as HTMLElement;
    issues.replaceChildren();
    if (!scored) return;

    const events = (scored.top_evidence.events || []).slice(0, 5);
    const alerts = (scored.top_evidence.alerts || []).slice(0, 5);
    [...events, ...alerts].forEach((item: any) => {
      const btn = document.createElement('button');
      btn.className = 'issue';
      btn.textContent = `${item.title || item.hazard_type} (${item.event_type || 'alert'})`;
      btn.onclick = () => {
        const coords = item.geometry?.coordinates;
        if (Array.isArray(coords) && coords.length === 2) {
          this.map.flyTo({ center: coords as Coord, zoom: 7, duration: 700 });
        }
      };
      issues.appendChild(btn);
    });
  }

  private async renderFallback(route: RouteOption): Promise<void> {
    const routingApi = this.getRoutingApiBase();
    const origin = this.parsePoint((this.container.querySelector('#origin') as HTMLInputElement).value);
    const response = await this.safeFetchJson<any>(`${routingApi}/routing/isochrone`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ payload: { locations: [{ lat: origin.lat, lon: origin.lon }], contours: [{ time: 90 }], costing: 'auto', polygons: true } }),
    });
    if (!response?.feature_collection) return;
    const hubs = getTopContainerPorts(12)
      .map((hub, idx) => ({ name: hub.name, score: Number((route.summary_risk.total + idx * 2).toFixed(1)) }))
      .sort((a, b) => a.score - b.score)
      .slice(0, 6);

    if (this.map.getSource('fallback-isochrone')) {
      (this.map.getSource('fallback-isochrone') as maplibregl.GeoJSONSource).setData(response.feature_collection as any);
    } else {
      this.map.addSource('fallback-isochrone', { type: 'geojson', data: response.feature_collection as any });
      this.map.addLayer({ id: 'fallback-isochrone-fill', type: 'fill', source: 'fallback-isochrone', paint: { 'fill-color': '#4cc9f0', 'fill-opacity': 0.12 } });
      this.map.addLayer({ id: 'fallback-isochrone-line', type: 'line', source: 'fallback-isochrone', paint: { 'line-color': '#4cc9f0', 'line-width': 2 } });
    }
    const issues = this.container.querySelector('#issues') as HTMLElement;
    issues.replaceChildren();
    hubs.forEach((hub) => {
      const item = document.createElement('button');
      item.className = 'issue';
      item.textContent = `${hub.name} · score ${hub.score}`;
      issues.appendChild(item);
    });
  }

  private async renderMultiStop(route: RouteOption): Promise<void> {
    const routingApi = this.getRoutingApiBase();
    const stopsInput = (this.container.querySelector('#stops') as HTMLTextAreaElement).value;
    const stopLines = stopsInput.split('\n').map((line) => line.trim()).filter((line) => line.length > 0);

    let origin;
    let destination;
    let mids;
    try {
      origin = this.parsePoint((this.container.querySelector('#origin') as HTMLInputElement).value);
      destination = this.parsePoint((this.container.querySelector('#destination') as HTMLInputElement).value);
      mids = stopLines.map((line) => this.parsePoint(line));
    } catch (error) {
      this.setStatus(error instanceof Error ? `Multi-stop input error: ${error.message}` : 'Multi-stop input error');
      return;
    }

    if (!mids.length) {
      this.setStatus('Add at least one valid stop for Multi-stop mode');
      return;
    }

    const locations = [{ lat: origin.lat, lon: origin.lon }, ...mids.map((s) => ({ lat: s.lat, lon: s.lon })), { lat: destination.lat, lon: destination.lon }];
    const response = await this.safeFetchJson<any>(`${routingApi}/routing/optimized_route`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ payload: { locations, costing: 'auto' } }),
    });
    const geometry = response?.route?.geometry;
    if (!geometry) {
      this.setStatus('No optimized route returned for Multi-stop mode');
      return;
    }

    const fc = { type: 'FeatureCollection', features: [{ type: 'Feature', geometry, properties: { score: route.summary_risk.total } }] } as FeatureCollection;
    if (this.map.getSource('multi-stop-route')) {
      (this.map.getSource('multi-stop-route') as maplibregl.GeoJSONSource).setData(fc as any);
    } else {
      this.map.addSource('multi-stop-route', { type: 'geojson', data: fc as any });
      this.map.addLayer({ id: 'multi-stop-route-line', type: 'line', source: 'multi-stop-route', paint: { 'line-width': 6, 'line-color': ['interpolate', ['linear'], ['get', 'score'], 0, '#2dc937', 100, '#cc3232'] } });
    }
  }



  private getPlannerApiBase(): string {
    return (import.meta.env.VITE_PLANNER_API_URL || 'http://localhost:8091').replace(/\/$/, '');
  }

  private async runMitigation(): Promise<void> {
    if (!this.selectedRouteId) throw new Error('Select a route first');
    const route = this.routes.find((item) => item.id === this.selectedRouteId);
    if (!route) throw new Error('Selected route unavailable');
    const origin = this.parsePoint((this.container.querySelector('#origin') as HTMLInputElement).value);
    const destination = this.parsePoint((this.container.querySelector('#destination') as HTMLInputElement).value);
    const depart = this.parseDateInput((this.container.querySelector('#depart') as HTMLInputElement).value, 'Depart time');
    const arrive = this.parseDateInput((this.container.querySelector('#arrive') as HTMLInputElement).value, 'Arrive by');
    const risk = Number((this.container.querySelector('#risk') as HTMLInputElement).value);
    const response = await this.safeFetchJson<MitigationResponse>(`${this.getPlannerApiBase()}/agent/mitigation`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ shipment: { origin, destination, depart_time: depart, arrive_by: arrive, mode: 'auto', risk_appetite: risk }, selected_route: { id: route.id, geometry: route.geometry } }),
    });
    if (!response) return;
    this.mitigation = response;
    this.renderMitigationPanel();
  }

  private renderMitigationPanel(): void {
    const container = this.container.querySelector('#mitigation-panel') as HTMLElement;
    if (!container) return;
    container.replaceChildren();
    if (!this.mitigation) return;

    const summary = document.createElement('div');
    summary.innerHTML = `<h4>Mitigation</h4><div>Baseline risk ${this.mitigation.baseline.risk_total.toFixed(1)} → Recommended <b>${this.mitigation.recommended_option_id}</b></div>`;
    container.appendChild(summary);

    this.mitigation.options.forEach((option) => {
      const row = document.createElement('div');
      row.className = 'issue';
      const topWin = this.mitigation?.robustness.win_rate.find((item) => item.option_id === option.option_id)?.win_pct ?? 0;
      row.innerHTML = `<div><b>${option.label}</b> · Δη ${option.delta_eta_hours.toFixed(1)}h · Δrisk ${option.delta_risk.toFixed(1)} · win ${topWin.toFixed(1)}%</div>`;
      const apply = document.createElement('button');
      apply.textContent = 'Apply option';
      apply.onclick = () => this.applyMitigationOption(option);
      row.appendChild(apply);
      const citations = document.createElement('div');
      option.citations.slice(0, 3).forEach((url) => {
        const link = document.createElement('a');
        link.href = url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = 'citation';
        citations.appendChild(link);
        citations.appendChild(document.createTextNode(' '));
      });
      row.appendChild(citations);
      container.appendChild(row);
    });
  }

  private applyMitigationOption(option: MitigationOption): void {
    const selected = this.routes.find((route) => route.id === this.selectedRouteId);
    if (!selected) return;
    selected.geometry = option.geometry;
    selected.eta_hours = option.eta_hours;
    selected.summary_risk.total = option.risk_total;
    this.renderRoutesLayer();
    this.selectRoute(selected.id, false);

    const evidence = this.container.querySelector('#evidence') as HTMLElement;
    evidence.replaceChildren();
    ['incidents', 'alerts', 'hazards'].forEach((bucket) => {
      const section = document.createElement('div');
      section.innerHTML = `<strong>${bucket}</strong>`;
      const list = document.createElement('ul');
      (option.evidence as any)[bucket].slice(0, 6).forEach((item: any) => {
        const li = document.createElement('li');
        li.textContent = String(item.title || item.type || item.message || item.id);
        list.appendChild(li);
      });
      section.appendChild(list);
      evidence.appendChild(section);
    });
    this.setStatus('Mitigation option applied');
  }

  private async loadEvidenceLayers(): Promise<void> {
    const api = this.getCompoundApiBase();
    const [incidents, alerts, hazards] = await Promise.all([
      this.safeFetchJson<FeatureCollection>(`${api}/compound/incidents?since_hours=72`),
      this.safeFetchJson<FeatureCollection>(`${api}/compound/alerts?run_id=latest&timestep=0`),
      this.safeFetchJson<FeatureCollection>(`${api}/compound/hazards?run_id=latest&timestep=0`),
    ]);

    this.map.addSource('incidents', { type: 'geojson', data: incidents ?? { type: 'FeatureCollection', features: [] }, cluster: true, clusterRadius: 40 });
    this.map.addSource('alerts', { type: 'geojson', data: alerts ?? { type: 'FeatureCollection', features: [] }, cluster: true, clusterRadius: 40 });
    this.map.addSource('hazards', { type: 'geojson', data: hazards ?? { type: 'FeatureCollection', features: [] } });
    this.map.addLayer({ id: 'hazards-fill', type: 'fill', source: 'hazards', paint: { 'fill-color': '#f94144', 'fill-opacity': 0.15 } });

    this.addClusterLayers('incidents', '#00bbf9');
    this.addClusterLayers('alerts', '#ff006e');
  }


  private getCompoundApiBase(): string {
    return (import.meta.env.VITE_COMPOUND_API_URL || 'http://localhost:8090').replace(/\/$/, '');
  }

  private async createAoiFromCenter(): Promise<void> {
    const center = this.map.getCenter();
    const radiusKm = Number((this.container.querySelector('#aoi-radius') as HTMLInputElement).value || '80');
    const name = (this.container.querySelector('#aoi-name') as HTMLInputElement).value || 'AOI';
    const latDelta = radiusKm / 111;
    const latRadians = (center.lat * Math.PI) / 180;
    const lonDelta = radiusKm / (111 * Math.max(Math.cos(latRadians), 0.01));
    const poly = { type: 'Polygon', coordinates: [[[center.lng - lonDelta, center.lat - latDelta], [center.lng + lonDelta, center.lat - latDelta], [center.lng + lonDelta, center.lat + latDelta], [center.lng - lonDelta, center.lat + latDelta], [center.lng - lonDelta, center.lat - latDelta]]] };
    await this.safeFetchJson(`${this.getCompoundApiBase()}/aois`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, geometry: poly, country_tags: [] }) });
    await this.refreshWatchlists();
  }

  private async refreshWatchlists(): Promise<void> {
    const aois = (await this.safeFetchJson<any[]>(`${this.getCompoundApiBase()}/aois`)) || [];
    const list = this.container.querySelector('#aoi-list') as HTMLElement;
    list.replaceChildren();
    this.aoiGeometries.clear();
    for (const aoi of aois) {
      const btn = document.createElement('button');
      btn.className = 'issue';
      btn.textContent = `${aoi.name} · risk ${Number(aoi.current_risk_score || 0).toFixed(1)}`;
      const aoiId = String(aoi.id);
      this.aoiGeometries.set(aoiId, aoi.geometry);
      btn.addEventListener('click', () => {
        this.selectedAoiId = aoiId;
        const geometry = this.aoiGeometries.get(aoiId);
        if (geometry) this.renderAoiGeometry(geometry);
        this.refreshChanges().catch(console.error);
      });
      list.appendChild(btn);
      if (!this.selectedAoiId) this.selectedAoiId = aoiId;
    }
    await this.refreshChanges();
  }

  private renderAoiGeometry(geometry: any): void {
    const fc = { type: 'FeatureCollection', features: [{ type: 'Feature', geometry, properties: {} }] };
    if (this.map.getSource('aoi-active')) (this.map.getSource('aoi-active') as maplibregl.GeoJSONSource).setData(fc as any);
    else {
      this.map.addSource('aoi-active', { type: 'geojson', data: fc as any });
      this.map.addLayer({ id: 'aoi-active-fill', type: 'fill', source: 'aoi-active', paint: { 'fill-color': '#f59e0b', 'fill-opacity': 0.15 } });
      this.map.addLayer({ id: 'aoi-active-line', type: 'line', source: 'aoi-active', paint: { 'line-color': '#f59e0b', 'line-width': 2 } });
    }
  }

  private async createSnapshot(): Promise<void> {
    if (!this.selectedAoiId) return;
    await this.safeFetchJson(`${this.getCompoundApiBase()}/aois/${this.selectedAoiId}/snapshot`, { method: 'POST' });
    await this.refreshWatchlists();
  }

  private async refreshChanges(): Promise<void> {
    if (!this.selectedAoiId) return;
    const changes = await this.safeFetchJson<any>(`${this.getCompoundApiBase()}/aois/${this.selectedAoiId}/changes?since_hours=168`);
    const box = this.container.querySelector('#aoi-changes') as HTMLElement;
    box.replaceChildren();
    for (const item of (changes?.items || [])) {
      const btn = document.createElement('button');
      btn.className = 'issue';
      btn.textContent = item.delta.human_readable?.summary || `Δ risk ${item.delta.risk_change}`;
      btn.addEventListener('click', () => {
        if (!this.selectedAoiId) return;
        const geometry = this.aoiGeometries.get(this.selectedAoiId);
        if (geometry) this.renderAoiGeometry(geometry);
      });
      box.appendChild(btn);
    }
  }

  private async generateMemo(): Promise<void> {
    if (!this.selectedAoiId) return;
    const changes = await this.safeFetchJson<any>(`${this.getCompoundApiBase()}/aois/${this.selectedAoiId}/changes?since_hours=168`);
    const latest = changes?.items?.[0];
    const fallback = latest ? `AOI update: ${latest.delta.human_readable?.summary || 'No summary'}` : 'No recent AOI deltas';
    const memo = await this.safeFetchJson<{ memo?: string }>(`${this.getCompoundApiBase()}/agent/brief`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt: fallback }) });
    if (memo) {
      this.setStatus('Memo generated successfully');
    } else {
      this.setStatus(`Memo generation failed. ${fallback}`);
    }
  }

  private addClusterLayers(sourceId: string, color: string): void {
    this.map.addLayer({ id: `${sourceId}-clusters`, type: 'circle', source: sourceId, filter: ['has', 'point_count'], paint: { 'circle-color': color, 'circle-radius': ['step', ['get', 'point_count'], 12, 10, 18, 30, 24], 'circle-opacity': 0.6 } });
    this.map.addLayer({ id: `${sourceId}-count`, type: 'symbol', source: sourceId, filter: ['has', 'point_count'], layout: { 'text-field': '{point_count_abbreviated}', 'text-size': 12 } });
    this.map.addLayer({ id: `${sourceId}-points`, type: 'circle', source: sourceId, filter: ['!', ['has', 'point_count']], paint: { 'circle-color': color, 'circle-radius': 5 } });

    this.map.on('click', `${sourceId}-clusters`, (e) => {
      const feature = this.map.queryRenderedFeatures(e.point, { layers: [`${sourceId}-clusters`] })[0];
      if (!feature) return;
      const clusterId = feature.properties?.cluster_id;
      (this.map.getSource(sourceId) as any).getClusterExpansionZoom(clusterId, (err: Error, zoom: number) => {
        if (!err) this.map.easeTo({ center: (feature.geometry as any).coordinates, zoom, duration: 500 });
      });
    });

    this.map.on('mousemove', `${sourceId}-points`, (e) => {
      const f = e.features?.[0] as any;
      if (!f) return;
      const p = f.properties || {};
      this.popup
        .setLngLat((f.geometry as any).coordinates)
        .setDOMContent(this.createPopupNode([
          String(p.event_type || p.alert_type || 'Signal'),
          String(p.title || 'Untitled'),
          `severity ${p.severity ?? '-'} conf ${p.confidence ?? '-'}`,
        ], p.url))
        .addTo(this.map);
    });
  }
}

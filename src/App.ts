import maplibregl, { LngLatBoundsLike, Map as MaplibreMap, Popup } from 'maplibre-gl';

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

type RouteScore = {
  total_risk: number;
  segment_scores: Array<{ segment_index: number; score: number; geometry: { type: 'LineString'; coordinates: Coord[] } }>;
  top_evidence: { events: Array<any>; alerts: Array<any>; hazards: Array<any> };
};

export class App {
  private container: HTMLElement;
  private map!: MaplibreMap;
  private popup = new Popup({ closeButton: false, closeOnClick: false });
  private routes: RouteOption[] = [];
  private selectedRouteId: string | null = null;
  private scoreByRoute = new globalThis.Map<string, RouteScore>();

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
      </aside>
      <aside class="panel panel-right"><h3>Route Options</h3><div id="route-cards"></div><h4>Issues along route</h4><div id="issues"></div></aside>
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

  private bindUI(): void {
    this.container.querySelector('#generate')?.addEventListener('click', () => {
      this.generateRoutes().catch((error: unknown) => {
        this.setStatus(error instanceof Error ? error.message : 'Failed to generate routes');
      });
    });
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
    const api = (import.meta.env.VITE_COMPOUND_API_URL || 'http://localhost:8090').replace(/\/$/, '');
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

    this.renderRouteCards();
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

  private async loadEvidenceLayers(): Promise<void> {
    const api = (import.meta.env.VITE_COMPOUND_API_URL || 'http://localhost:8090').replace(/\/$/, '');
    const [events, alerts, hazards] = await Promise.all([
      this.safeFetchJson<FeatureCollection>(`${api}/compound/events?since_hours=72`),
      this.safeFetchJson<FeatureCollection>(`${api}/compound/alerts?run_id=latest&timestep=0`),
      this.safeFetchJson<FeatureCollection>(`${api}/compound/hazards?run_id=latest&timestep=0`),
    ]);

    this.map.addSource('events', { type: 'geojson', data: events ?? { type: 'FeatureCollection', features: [] }, cluster: true, clusterRadius: 40 });
    this.map.addSource('alerts', { type: 'geojson', data: alerts ?? { type: 'FeatureCollection', features: [] }, cluster: true, clusterRadius: 40 });
    this.map.addSource('hazards', { type: 'geojson', data: hazards ?? { type: 'FeatureCollection', features: [] } });
    this.map.addLayer({ id: 'hazards-fill', type: 'fill', source: 'hazards', paint: { 'fill-color': '#f94144', 'fill-opacity': 0.15 } });

    this.addClusterLayers('events', '#00bbf9');
    this.addClusterLayers('alerts', '#ff006e');
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

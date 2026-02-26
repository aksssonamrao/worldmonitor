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


export class App {
  private container: HTMLElement;
  private map!: MaplibreMap;
  private popup = new Popup({ closeButton: false, closeOnClick: false });
  private routes: RouteOption[] = [];
  private selectedRouteId: string | null = null;
  private scoreByRoute = new globalThis.Map<string, any>();

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

  private bindUI(): void {
    this.container.querySelector('#generate')?.addEventListener('click', () => this.generateRoutes());
  }

  private parsePoint(input: string): { lat: number; lon: number } {
    const [lat = 0, lon = 0] = input.split(',').map(Number);
    return { lat, lon };
  }

  private async generateRoutes(): Promise<void> {
    const origin = this.parsePoint((this.container.querySelector('#origin') as HTMLInputElement).value);
    const destination = this.parsePoint((this.container.querySelector('#destination') as HTMLInputElement).value);
    const depart = new Date((this.container.querySelector('#depart') as HTMLInputElement).value).toISOString();
    const arrive = new Date((this.container.querySelector('#arrive') as HTMLInputElement).value).toISOString();
    const risk = Number((this.container.querySelector('#risk') as HTMLInputElement).value);
    const plannerApi = (import.meta.env.VITE_COMPOUND_API_URL || 'http://localhost:8090').replace(/\/$/, '');
    const payload = { origin, destination, depart_time: depart, arrive_by: arrive, risk_appetite: risk };
    const response = await fetch(`${plannerApi}/routes/options`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await response.json();
    this.routes = data.routes;
    await Promise.all(this.routes.map(async (route) => {
      const scoreResp = await fetch(`${plannerApi}/routes/score`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ geometry: route.geometry, depart_time: depart, arrive_by: arrive }) });
      this.scoreByRoute.set(route.id, await scoreResp.json());
    }));
    this.renderRouteCards();
    this.renderRoutesLayer();
  }

  private renderRouteCards(): void {
    const cards = this.container.querySelector('#route-cards') as HTMLElement;
    cards.innerHTML = '';
    for (const route of this.routes) {
      const el = document.createElement('button');
      el.className = `route-card ${this.selectedRouteId === route.id ? 'selected' : ''}`;
      el.innerHTML = `<strong>${route.name}</strong><span>${route.distance_km.toFixed(1)} km · ${route.eta_hours.toFixed(1)}h</span><span>Risk ${route.summary_risk.total.toFixed(1)}</span>`;
      el.addEventListener('click', () => this.selectRoute(route.id, true));
      cards.appendChild(el);
    }
  }

  private renderRoutesLayer(): void {
    const features = this.routes.map((route) => ({ type: 'Feature', geometry: route.geometry, properties: { ...route } }));
    const fc = { type: 'FeatureCollection', features } as any;
    if (this.map.getSource('routes')) {
      (this.map.getSource('routes') as any).setData(fc);
    } else {
      this.map.addSource('routes', { type: 'geojson', data: fc });
      this.map.addLayer({ id: 'routes-line', type: 'line', source: 'routes', paint: { 'line-color': ['match', ['get', 'name'], 'Fastest', '#a8dadc', 'Balanced', '#f4a261', '#2a9d8f'], 'line-width': ['case', ['==', ['get', 'id'], this.selectedRouteId || ''], 6, 3], 'line-opacity': ['case', ['==', ['get', 'id'], this.selectedRouteId || ''], 1, 0.4], 'line-dasharray': ['match', ['get', 'name'], 'Fastest', ['literal', [1, 0]], 'Balanced', ['literal', [2, 1]], ['literal', [0.5, 1.5]]], }, layout: { 'line-cap': 'round', 'line-join': 'round' } });
      this.map.on('mousemove', 'routes-line', (e) => {
        const f = e.features?.[0];
        if (!f) return;
        const props = f.properties as any;
      this.popup.setLngLat(e.lngLat).setHTML(`<b>${props.name}</b><br/>${Number(props.distance_km).toFixed(1)} km<br/>ETA ${Number(props.eta_hours).toFixed(1)}h<br/>Risk ${Number(props.summary_risk?.total ?? 0).toFixed(1)}`).addTo(this.map);
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
      const bounds = route.geometry.coordinates.reduce((b, c) => b.extend(c as [number, number]), new maplibregl.LngLatBounds(route.geometry.coordinates[0] as [number, number], route.geometry.coordinates[0] as [number, number]));
      this.map.fitBounds(bounds as LngLatBoundsLike, { padding: 120, duration: 700 });
    }
    this.renderGradient(routeId);
    this.renderIssues(routeId);
  }

  private renderGradient(routeId: string): void {
    const scored = this.scoreByRoute.get(routeId);
    if (!scored) return;
    const features = scored.segment_scores.map((s: any) => ({ type: 'Feature', geometry: s.geometry, properties: { score: s.score } }));
    const fc = { type: 'FeatureCollection', features } as any;
    if (this.map.getSource('selected-gradient')) {
      (this.map.getSource('selected-gradient') as any).setData(fc);
    } else {
      this.map.addSource('selected-gradient', { type: 'geojson', data: fc });
      this.map.addLayer({ id: 'selected-gradient-line', type: 'line', source: 'selected-gradient', paint: { 'line-width': 8, 'line-color': ['interpolate', ['linear'], ['get', 'score'], 0, '#2dc937', 50, '#e7b416', 100, '#cc3232'], 'line-opacity': 0.95 } });
    }
    const e = this.container.querySelector('#evidence') as HTMLElement;
    e.innerHTML = `<pre>${JSON.stringify(scored.top_evidence, null, 2)}</pre>`;
  }

  private renderIssues(routeId: string): void {
    const scored = this.scoreByRoute.get(routeId);
    const issues = this.container.querySelector('#issues') as HTMLElement;
    const events = (scored?.top_evidence?.events || []).slice(0, 5);
    const alerts = (scored?.top_evidence?.alerts || []).slice(0, 5);
    issues.innerHTML = '';
    [...events, ...alerts].forEach((item: any) => {
      const btn = document.createElement('button');
      btn.className = 'issue';
      btn.textContent = `${item.title || item.hazard_type} (${item.event_type || 'alert'})`;
      btn.onclick = () => {
        const c = item.geometry?.coordinates;
        if (c) this.map.flyTo({ center: c, zoom: 7, duration: 700 });
      };
      issues.appendChild(btn);
    });
  }

  private async loadEvidenceLayers(): Promise<void> {
    const api = (import.meta.env.VITE_COMPOUND_API_URL || 'http://localhost:8090').replace(/\/$/, '');
    const [events, alerts, hazards] = await Promise.all([
      fetch(`${api}/compound/events?since_hours=72`).then((r) => r.json()),
      fetch(`${api}/compound/alerts?run_id=latest&timestep=0`).then((r) => r.json()),
      fetch(`${api}/compound/hazards?run_id=latest&timestep=0`).then((r) => r.json()),
    ]);
    this.map.addSource('events', { type: 'geojson', data: events, cluster: true, clusterRadius: 40 });
    this.map.addSource('alerts', { type: 'geojson', data: alerts, cluster: true, clusterRadius: 40 });
    this.map.addSource('hazards', { type: 'geojson', data: hazards });
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
        if (err) return;
        this.map.easeTo({ center: (feature.geometry as any).coordinates, zoom, duration: 500 });
      });
    });
    this.map.on('mousemove', `${sourceId}-points`, (e) => {
      const f = e.features?.[0] as any;
      if (!f) return;
      const p = f.properties || {};
      this.popup.setLngLat((f.geometry as any).coordinates).setHTML(`<b>${p.event_type || p.alert_type}</b><br/>${p.title || 'Untitled'}<br/>severity ${p.severity ?? '-'} conf ${p.confidence ?? '-'}<br/><a href="${p.url}" target="_blank">source↗</a>`).addTo(this.map);
    });
  }
}

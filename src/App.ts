type Feature = {
  type: 'Feature';
  geometry: { type: string; coordinates: number[] };
  properties: Record<string, unknown>;
};

export class App {
  private container: HTMLElement;
  private eventsEnabled = true;

  constructor(containerId: string) {
    const container = document.getElementById(containerId);
    if (!container) {
      throw new Error(`Missing app container: ${containerId}`);
    }
    this.container = container;
  }

  async init(): Promise<void> {
    this.container.innerHTML = `
      <main style="min-height:100vh;padding:24px;font-family:Inter,system-ui,sans-serif;background:#0b1220;color:#e6edf7;">
        <h1 style="margin:0 0 12px;font-size:28px;">World Monitor — Compound Hazards + Events</h1>
        <label style="display:flex;gap:8px;align-items:center;margin:12px 0 20px;">
          <input id="events-toggle" type="checkbox" checked />
          Events layer
        </label>
        <section style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
          <div><h2 style="margin:0 0 8px;">Events</h2><div id="events-panel"></div></div>
          <div><h2 style="margin:0 0 8px;">Compound Alerts</h2><div id="alerts-panel"></div></div>
        </section>
      </main>
    `;
    const toggle = this.container.querySelector<HTMLInputElement>('#events-toggle');
    toggle?.addEventListener('change', async () => {
      this.eventsEnabled = !!toggle.checked;
      await this.renderData();
    });
    await this.renderData();
  }

  private async renderData(): Promise<void> {
    const eventsPanel = this.container.querySelector<HTMLElement>('#events-panel');
    const alertsPanel = this.container.querySelector<HTMLElement>('#alerts-panel');
    if (!eventsPanel || !alertsPanel) return;

    const [events, alerts] = await Promise.all([
      this.eventsEnabled ? this.fetchFeatures('/compound/events?since_hours=72') : Promise.resolve([]),
      this.fetchFeatures('/compound/alerts?run_id=latest&timestep=0'),
    ]);

    eventsPanel.innerHTML = this.renderList(
      events,
      (f) => `${f.properties.title} · ${f.properties.event_type} · ${f.properties.country} · <a href="${f.properties.url}" target="_blank">source</a>`,
    );
    alertsPanel.innerHTML = this.renderList(
      alerts,
      (f) => `${f.properties.title} · ${f.properties.hazard_type} · score=${Number(f.properties.score).toFixed(1)} · <a href="${f.properties.url}" target="_blank">source</a>`,
    );
  }

  private renderList(features: Feature[], mapper: (feature: Feature) => string): string {
    if (!features.length) return '<p style="opacity:.75">No items</p>';
    return `<ul style="margin:0;padding-left:18px;display:flex;flex-direction:column;gap:6px;">${features
      .map((f) => `<li>${mapper(f)}</li>`)
      .join('')}</ul>`;
  }

  private async fetchFeatures(path: string): Promise<Feature[]> {
    const baseUrl = (import.meta.env.VITE_COMPOUND_API_URL || 'http://localhost:8090').replace(/\/$/, '');
    const response = await fetch(`${baseUrl}${path}`);
    if (!response.ok) return [];
    const payload = await response.json();
    return payload.features || [];
  }
}

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

    eventsPanel.replaceChildren(this.renderList(events, (f) => this.createEventItem(f)));
    alertsPanel.replaceChildren(this.renderList(alerts, (f) => this.createAlertItem(f)));
  }

  private renderList(features: Feature[], mapper: (feature: Feature) => HTMLElement): HTMLElement {
    if (!features.length) {
      const p = document.createElement('p');
      p.style.opacity = '0.75';
      p.textContent = 'No items';
      return p;
    }
    const list = document.createElement('ul');
    list.style.margin = '0';
    list.style.paddingLeft = '18px';
    list.style.display = 'flex';
    list.style.flexDirection = 'column';
    list.style.gap = '6px';
    for (const feature of features) {
      const item = document.createElement('li');
      item.appendChild(mapper(feature));
      list.appendChild(item);
    }
    return list;
  }

  private createEventItem(feature: Feature): HTMLElement {
    const wrapper = document.createElement('span');
    wrapper.textContent = `${String(feature.properties.title ?? 'Untitled')} · ${String(feature.properties.event_type ?? 'OTHER')} · ${String(feature.properties.country ?? 'Unknown')} · `;
    wrapper.appendChild(this.createSourceLink(feature.properties.url));
    return wrapper;
  }

  private createAlertItem(feature: Feature): HTMLElement {
    const wrapper = document.createElement('span');
    const score = Number(feature.properties.score ?? 0);
    wrapper.textContent = `${String(feature.properties.title ?? 'Untitled')} · ${String(feature.properties.hazard_type ?? 'N/A')} · score=${score.toFixed(1)} · `;
    wrapper.appendChild(this.createSourceLink(feature.properties.url));
    return wrapper;
  }

  private createSourceLink(urlValue: unknown): HTMLAnchorElement | Text {
    const url = typeof urlValue === 'string' ? urlValue : '';
    const parsed = this.safeHttpUrl(url);
    if (!parsed) {
      return document.createTextNode('source unavailable');
    }
    const anchor = document.createElement('a');
    anchor.href = parsed;
    anchor.textContent = 'source';
    anchor.target = '_blank';
    anchor.rel = 'noopener noreferrer';
    return anchor;
  }

  private safeHttpUrl(input: string): string | null {
    try {
      const parsed = new URL(input);
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
        return parsed.toString();
      }
    } catch {
      return null;
    }
    return null;
  }

  private async fetchFeatures(path: string): Promise<Feature[]> {
    const baseUrl = (import.meta.env.VITE_COMPOUND_API_URL || 'http://localhost:8090').replace(/\/$/, '');
    try {
      const response = await fetch(`${baseUrl}${path}`);
      if (!response.ok) {
        const body = await response.text();
        console.error('fetchFeatures request failed', { path, status: response.status, statusText: response.statusText, body });
        return [];
      }
      const payload = await response.json();
      if (!payload || !Array.isArray(payload.features)) {
        console.error('fetchFeatures invalid payload', { path, payload });
        return [];
      }
      return payload.features as Feature[];
    } catch (error) {
      console.error('fetchFeatures exception', { path, error });
      return [];
    }
  }
}

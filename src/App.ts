export class App {
  private container: HTMLElement;

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
        <h1 style="margin:0 0 12px;font-size:28px;">World Monitor — Route Risk Planner</h1>
        <p style="margin:0 0 8px;max-width:900px;line-height:1.5;">
          The repo has been reduced to a focused route-risk scope. Frontend modules that were tied to
          markets, crypto, prediction markets, live video, browser-side ML, and dual-variant tech routing
          were intentionally removed.
        </p>
        <p style="margin:0;max-width:900px;line-height:1.5;opacity:.85;">
          Use Docker Compose with the compound API for Google Weather hazard generation.
        </p>
      </main>
    `;
  }
}

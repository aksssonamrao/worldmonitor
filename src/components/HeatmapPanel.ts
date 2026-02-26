import { Panel } from './Panel';
export class HeatmapPanel extends Panel {
  constructor() { super({ id: 'heatmap', title: 'Sector Heatmap' }); }
  renderHeatmap(): void {}
}

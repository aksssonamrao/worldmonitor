import { Panel } from './Panel';
import type { PredictionMarket } from '@/types';
export class PredictionPanel extends Panel {
  constructor(){ super({ id:'forecasts', title:'Predictions' }); }
  renderPredictions(_data: PredictionMarket[]): void { this.setContent('<div class="panel-placeholder">Removed</div>'); }
}

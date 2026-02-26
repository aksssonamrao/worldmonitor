import { Panel } from './Panel';

export class LiveNewsPanel extends Panel {
  constructor() {
    super({ id: 'live-news', title: 'Live News', showCount: false, trackActivity: false });
    const body = this.element.querySelector('.panel-content');
    if (body) {
      body.innerHTML = '<div class="muted">Live video streams removed. Use the routing-focused news feeds.</div>';
    }
  }
}

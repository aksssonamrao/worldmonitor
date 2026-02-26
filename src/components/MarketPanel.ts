import { Panel } from './Panel';
import type { MarketData } from '@/types';
import { formatPrice, formatChange, getChangeClass, getHeatmapClass } from '@/utils';
import { escapeHtml } from '@/utils/sanitize';

export class MarketPanel extends Panel {
  constructor() {
    super({ id: 'markets', title: 'Markets' });
  }

  public renderMarkets(data: MarketData[]): void {
    if (data.length === 0) {
      this.showError('Failed to load market data');
      return;
    }

    const html = data
      .map(
        (stock) => `
      <div class="market-item">
        <div class="market-info">
          <span class="market-name">${escapeHtml(stock.name)}</span>
          <span class="market-symbol">${escapeHtml(stock.display)}</span>
        </div>
        <div class="market-data">
          <span class="market-price">${formatPrice(stock.price!)}</span>
          <span class="market-change ${getChangeClass(stock.change!)}">${formatChange(stock.change!)}</span>
        </div>
      </div>
    `
      )
      .join('');

    this.setContent(html);
  }
}

export class HeatmapPanel extends Panel {
  constructor() {
    super({ id: 'heatmap', title: 'Sector Heatmap' });
  }

  public renderHeatmap(data: Array<{ name: string; change: number | null }>): void {
    const validData = data.filter((d) => d.change !== null);

    if (validData.length === 0) {
      this.showError('Failed to load sector data');
      return;
    }

    const html =
      '<div class="heatmap">' +
      validData
        .map(
          (sector) => `
        <div class="heatmap-cell ${getHeatmapClass(sector.change!)}">
          <div class="sector-name">${escapeHtml(sector.name)}</div>
          <div class="sector-change ${getChangeClass(sector.change!)}">${formatChange(sector.change!)}</div>
        </div>
      `
        )
        .join('') +
      '</div>';

    this.setContent(html);
  }
}

export class CommoditiesPanel extends Panel {
  constructor() {
    super({ id: 'commodities', title: 'Commodities / VIX' });
  }

  public renderCommodities(data: Array<{ display: string; price: number | null; change: number | null }>): void {
    const validData = data.filter((d) => d.price !== null);

    if (validData.length === 0) {
      this.showError('Failed to load commodities');
      return;
    }

    const html =
      '<div class="commodities-grid">' +
      validData
        .map(
          (c) => `
        <div class="commodity-item">
          <div class="commodity-name">${escapeHtml(c.display)}</div>
          <div class="commodity-price">${formatPrice(c.price!)}</div>
          <div class="commodity-change ${getChangeClass(c.change!)}">${formatChange(c.change!)}</div>
        </div>
      `
        )
        .join('') +
      '</div>';

    this.setContent(html);
  }
}

export class DigitalPanel extends Panel {
  constructor() { super({ id: 'digital', title: 'Digital' }); }
  public renderDigital(_data: Array<{name:string;symbol:string;price:number;change:number}>): void {
    this.setContent('<div class="panel-placeholder">Removed</div>');
  }
}

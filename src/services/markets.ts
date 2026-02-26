import type { MarketData } from '@/types';
import { API_URLS } from '@/config';
import { fetchWithProxy } from '@/utils';

interface FinnhubQuote {
  symbol: string;
  price: number;
  change: number;
  changePercent: number;
  high: number;
  low: number;
  open: number;
  previousClose: number;
  timestamp: number;
  error?: string;
}

interface FinnhubResponse {
  quotes: FinnhubQuote[];
  error?: string;
}

interface YahooFinanceResponse {
  chart: {
    result: Array<{
      meta: {
        regularMarketPrice: number;
        chartPreviousClose?: number;
        previousClose?: number;
      };
    }>;
  };
}

// Symbols that need Yahoo Finance (indices and futures not supported by Finnhub free tier)
const YAHOO_ONLY_SYMBOLS = new Set([
  '^GSPC', '^DJI', '^IXIC', '^VIX',
  'GC=F', 'CL=F', 'NG=F', 'SI=F', 'HG=F',
]);

let lastSuccessfulResults: MarketData[] = [];

async function fetchFromFinnhub(
  symbols: Array<{ symbol: string; name: string; display: string }>
): Promise<MarketData[]> {
  const symbolList = symbols.map(s => s.symbol);
  const url = API_URLS.finnhub(symbolList);

  try {
    const response = await fetchWithProxy(url);

    if (!response.ok) {
      console.warn(`[Markets] Finnhub returned ${response.status}`);
      return [];
    }

    const data: FinnhubResponse = await response.json();

    if (data.error) {
      console.warn(`[Markets] Finnhub error: ${data.error}`);
      return [];
    }

    const symbolMap = new Map(symbols.map(s => [s.symbol, s]));

    return data.quotes
      .filter(q => !q.error && q.price > 0)
      .map(q => {
        const info = symbolMap.get(q.symbol);
        return {
          symbol: q.symbol,
          name: info?.name || q.symbol,
          display: info?.display || q.symbol,
          price: q.price,
          change: q.changePercent,
        };
      });
  } catch (error) {
    console.error('[Markets] Finnhub fetch failed:', error);
    return [];
  }
}

async function fetchFromYahoo(
  symbol: string,
  name: string,
  display: string
): Promise<MarketData | null> {
  try {
    const url = API_URLS.yahooFinance(symbol);
    const response = await fetchWithProxy(url);

    if (!response.ok) return null;
    const data: YahooFinanceResponse = await response.json();

    const meta = data.chart.result[0]?.meta;
    if (!meta) return null;

    const price = meta.regularMarketPrice;
    const prevClose = meta.chartPreviousClose || meta.previousClose || price;
    const change = ((price - prevClose) / prevClose) * 100;

    return { symbol, name, display, price, change };
  } catch {
    return null;
  }
}

export async function fetchMultipleStocks(
  symbols: Array<{ symbol: string; name: string; display: string }>,
  options: {
    onBatch?: (results: MarketData[]) => void;
  } = {}
): Promise<MarketData[]> {
  // Split symbols into Finnhub-compatible and Yahoo-only
  const finnhubSymbols = symbols.filter(s => !YAHOO_ONLY_SYMBOLS.has(s.symbol));
  const yahooSymbols = symbols.filter(s => YAHOO_ONLY_SYMBOLS.has(s.symbol));

  const results: MarketData[] = [];

  // Fetch from Finnhub (batch request)
  if (finnhubSymbols.length > 0) {
    const finnhubResults = await fetchFromFinnhub(finnhubSymbols);
    results.push(...finnhubResults);
    options.onBatch?.(results);
  }

  // Fetch indices/commodities from Yahoo (parallel)
  if (yahooSymbols.length > 0) {
    const yahooResults = await Promise.all(
      yahooSymbols.map(s => fetchFromYahoo(s.symbol, s.name, s.display))
    );
    results.push(...yahooResults.filter((r): r is MarketData => r !== null));
    options.onBatch?.(results);
  }

  if (results.length > 0) {
    lastSuccessfulResults = results;
  }

  return results.length > 0 ? results : lastSuccessfulResults;
}

// Legacy single-symbol function (still used by some components)
export async function fetchStockQuote(
  symbol: string,
  name: string,
  display: string
): Promise<MarketData> {
  if (YAHOO_ONLY_SYMBOLS.has(symbol)) {
    const result = await fetchFromYahoo(symbol, name, display);
    return result || { symbol, name, display, price: null, change: null };
  }

  const results = await fetchFromFinnhub([{ symbol, name, display }]);
  return results[0] || { symbol, name, display, price: null, change: null };
}

export async function fetchDigital(): Promise<Array<{name:string;symbol:string;price:number;change:number}>> {
  return [];
}

export interface MarketData { symbol: string; name: string; display: string; price: number; change: number; percentChange: number; }
export async function fetchMultipleStocks(): Promise<MarketData[]> { return []; }
export async function fetchDigital(): Promise<MarketData[]> { return []; }

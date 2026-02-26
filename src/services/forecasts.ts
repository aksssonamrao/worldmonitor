import type { PredictionMarket } from '@/types';

export async function fetchPredictions(): Promise<PredictionMarket[]> { return []; }
export function getForecastStatus(): string { return 'disabled'; }
export async function fetchCountryMarkets(_country: string): Promise<PredictionMarket[]> { return []; }

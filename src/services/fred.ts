export interface FredSeries { id: string; title: string; value: number; previous: number; unit?: string; }

export async function fetchFredData(): Promise<FredSeries[]> { return []; }

export function getChangeClass(change: number): string {
  if (change > 0) return 'positive';
  if (change < 0) return 'negative';
  return 'neutral';
}

export function formatChange(change: number): string {
  const sign = change > 0 ? '+' : '';
  return `${sign}${change.toFixed(2)}%`;
}

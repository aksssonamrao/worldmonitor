export interface OilMetric { key: string; label: string; value: number; unit?: string; trend?: number; }
export async function fetchOilAnalytics(): Promise<OilMetric[]> { return []; }
export function formatOilValue(value: number, unit = ''): string { return `${value}${unit}`; }
export function getTrendIndicator(trend = 0): string { return trend > 0 ? '↑' : trend < 0 ? '↓' : '→'; }
export function getTrendColor(trend = 0): string { return trend > 0 ? '#44ff88' : trend < 0 ? '#ff6666' : '#a0a0a0'; }

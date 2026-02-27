export const API_URLS: any = {
  githubTrending: (language = 'python', since = 'daily') => `/api/github-trending?language=${encodeURIComponent(language)}&since=${encodeURIComponent(since)}`,
  hackernews: (type = 'top', limit = 30) => `/api/hackernews?type=${encodeURIComponent(type)}&limit=${limit}`,
};

export const REFRESH_INTERVALS = {
  headlines: 60000,
  map: 120000,
} as const;

export const MONITOR_COLORS = ['#44ff88', '#ff8844', '#4488ff', '#ff44ff', '#ffff44'];

export const STORAGE_KEYS = {
  panels: 'corridorone-panels',
  monitors: 'corridorone-monitors',
  mapLayers: 'corridorone-layers',
  disabledFeeds: 'corridorone-disabled-feeds',
} as const;

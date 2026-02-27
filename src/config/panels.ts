import type { PanelConfig, MapLayers } from '@/types';

export const DEFAULT_PANELS: Record<string, PanelConfig> = {
  map: { name: 'Global Map', enabled: true, priority: 1 },
  'live-news': { name: 'Live News', enabled: true, priority: 1 },
  insights: { name: 'AI Insights', enabled: true, priority: 1 },
  'strategic-posture': { name: 'AI Strategic Posture', enabled: true, priority: 1 },
  cii: { name: 'Country Instability', enabled: true, priority: 1 },
  'strategic-risk': { name: 'Strategic Risk Overview', enabled: true, priority: 1 },
  intel: { name: 'Intel Feed', enabled: true, priority: 1 },
  'gdelt-intel': { name: 'Live Intelligence', enabled: true, priority: 1 },
  cascade: { name: 'Infrastructure Cascade', enabled: true, priority: 1 },
  politics: { name: 'World News', enabled: true, priority: 1 },
  middleeast: { name: 'Middle East', enabled: true, priority: 1 },
  africa: { name: 'Africa', enabled: true, priority: 1 },
  latam: { name: 'Latin America', enabled: true, priority: 1 },
  asia: { name: 'Asia-Pacific', enabled: true, priority: 1 },
  energy: { name: 'Energy & Resources', enabled: true, priority: 1 },
  gov: { name: 'Government', enabled: true, priority: 1 },
  thinktanks: { name: 'Think Tanks', enabled: true, priority: 1 },
  monitors: { name: 'My Monitors', enabled: true, priority: 2 },
  'satellite-fires': { name: 'Fires', enabled: true, priority: 2 },
};

export const DEFAULT_MAP_LAYERS: MapLayers = {
  conflicts: true,bases: true,cables: false,pipelines: false,hotspots: true,ais: false,nuclear: true,irradiators: false,sanctions: true,weather: true,economic: true,waterways: true,outages: true,datacenters: false,protests: false,flights: false,military: true,natural: true,spaceports: false,minerals: false,fires: false,startupHubs: false,cloudRegions: false,accelerators: false,techHQs: false,techEvents: false,compoundRisk: false,
};
export const MOBILE_DEFAULT_MAP_LAYERS: MapLayers = { ...DEFAULT_MAP_LAYERS, bases: false, nuclear: false, economic: false, waterways: false, military: false };

export const MONITOR_COLORS = ['#44ff88','#ff8844','#4488ff','#ff44ff','#ffff44'];
export const STORAGE_KEYS = {
  panels: 'corridorone-panels', monitors: 'corridorone-monitors', mapLayers: 'corridorone-layers', disabledFeeds: 'corridorone-disabled-feeds',
} as const;

export const SITE_VARIANT = (import.meta.env.VITE_VARIANT || 'full') as string;

export {
  API_URLS,
  REFRESH_INTERVALS,
  MONITOR_COLORS,
  STORAGE_KEYS,
} from './variants/base';

export { SECTORS, COMMODITIES, MARKET_SYMBOLS } from './markets';
export { UNDERSEA_CABLES, MAP_URLS } from './geo';
export { AI_DATA_CENTERS } from './ai-datacenters';

export {
  SOURCE_TIERS,
  getSourceTier,
  SOURCE_TYPES,
  getSourceType,
  getSourcePropagandaRisk,
  ALERT_KEYWORDS,
  ALERT_EXCLUSIONS,
  type SourceRiskProfile,
  type SourceType,
  FEEDS,
  INTEL_SOURCES,
} from './feeds';

export {
  DEFAULT_PANELS,
  DEFAULT_MAP_LAYERS,
  MOBILE_DEFAULT_MAP_LAYERS,
} from './panels';

export {
  INTEL_HOTSPOTS,
  CONFLICT_ZONES,
  MILITARY_BASES,
  NUCLEAR_FACILITIES,
  APT_GROUPS,
  STRATEGIC_WATERWAYS,
  ECONOMIC_CENTERS,
  SANCTIONED_COUNTRIES,
  SPACEPORTS,
  CRITICAL_MINERALS,
} from './geo';

export { GAMMA_IRRADIATORS } from './irradiators';
export { PIPELINES, PIPELINE_COLORS } from './pipelines';
export { PORTS } from './ports';
export { MONITORED_AIRPORTS, FAA_AIRPORTS } from './airports';
export {
  ENTITY_REGISTRY,
  getEntityById,
  type EntityType,
  type EntityEntry,
} from './entities';

export {
  STARTUP_HUBS,
  ACCELERATORS,
  TECH_HQS,
  CLOUD_REGIONS,
  type StartupHub,
  type Accelerator,
  type TechHQ,
  type CloudRegion,
} from './tech-geo';

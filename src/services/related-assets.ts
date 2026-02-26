import type { RelatedAsset, NewsItem } from '@/types';

export const MAX_DISTANCE_KM = 500;

export function getRelatedAssets(_: NewsItem): RelatedAsset[] {
  return [];
}

export function getClusterAssetContext(): string {
  return '';
}

export function getAssetLabel(asset: RelatedAsset): string {
  return asset.name;
}

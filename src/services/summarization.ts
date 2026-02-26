/**
 * Summarization Service with Fallback Chain
 * Server-side Redis caching handles cross-user deduplication
 * Fallback: Groq -> OpenRouter
 */

import { SITE_VARIANT } from '@/config';

export type SummarizationProvider = 'groq' | 'openrouter' | 'cache';

export interface SummarizationResult {
  summary: string;
  provider: SummarizationProvider;
  cached: boolean;
}

export type ProgressCallback = (step: number, total: number, message: string) => void;

async function tryGroq(headlines: string[], geoContext?: string): Promise<SummarizationResult | null> {
  try {
    const response = await fetch('/api/groq-summarize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ headlines, mode: 'brief', geoContext, variant: SITE_VARIANT }),
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      if (data.fallback) return null;
      throw new Error(`Groq error: ${response.status}`);
    }

    const data = await response.json();
    const provider = data.cached ? 'cache' : 'groq';
    console.log(`[Summarization] ${provider === 'cache' ? 'Redis cache hit' : 'Groq success'}:`, data.model);
    return {
      summary: data.summary,
      provider: provider as SummarizationProvider,
      cached: !!data.cached,
    };
  } catch (error) {
    console.warn('[Summarization] Groq failed:', error);
    return null;
  }
}

async function tryOpenRouter(headlines: string[], geoContext?: string): Promise<SummarizationResult | null> {
  try {
    const response = await fetch('/api/openrouter-summarize', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ headlines, mode: 'brief', geoContext, variant: SITE_VARIANT }),
    });

    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      if (data.fallback) return null;
      throw new Error(`OpenRouter error: ${response.status}`);
    }

    const data = await response.json();
    const provider = data.cached ? 'cache' : 'openrouter';
    console.log(`[Summarization] ${provider === 'cache' ? 'Redis cache hit' : 'OpenRouter success'}:`, data.model);
    return {
      summary: data.summary,
      provider: provider as SummarizationProvider,
      cached: !!data.cached,
    };
  } catch (error) {
    console.warn('[Summarization] OpenRouter failed:', error);
    return null;
  }
}

/**
 * Generate a summary using the fallback chain: Groq -> OpenRouter
 * @param geoContext Optional geographic signal context to include in the prompt
 */
export async function generateSummary(
  headlines: string[],
  onProgress?: ProgressCallback,
  geoContext?: string
): Promise<SummarizationResult | null> {
  if (!headlines || headlines.length < 2) {
    return null;
  }

  const totalSteps = 2;

  // Step 1: Try Groq (fast, 14.4K/day with 8b-instant + Redis cache)
  onProgress?.(1, totalSteps, 'Connecting to Groq AI...');
  const groqResult = await tryGroq(headlines, geoContext);
  if (groqResult) {
    return groqResult;
  }

  // Step 2: Try OpenRouter (fallback, 50/day + Redis cache)
  onProgress?.(2, totalSteps, 'Trying OpenRouter...');
  const openRouterResult = await tryOpenRouter(headlines, geoContext);
  if (openRouterResult) {
    return openRouterResult;
  }


  console.warn('[Summarization] All providers failed');
  return null;
}


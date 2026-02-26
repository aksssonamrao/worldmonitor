export const ML_THRESHOLDS = {
  semanticClusterThreshold: 0.72,
  inferenceTimeoutMs: 3000,
  modelLoadTimeoutMs: 8000,
} as const;

export const MODEL_CONFIGS: Array<{ id: string; required: boolean }> = [];

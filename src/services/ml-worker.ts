export interface SentimentResult {
  label: 'positive' | 'negative' | 'neutral';
  score: number;
}

export interface NEREntity {
  text: string;
  type: string;
  confidence: number;
  start: number;
  end: number;
}

export const mlWorker = {
  async init(): Promise<boolean> { return false; },
  isAvailable: false,
  async unloadOptionalModels(): Promise<void> { return; },
  async classifySentiment(texts: string[]): Promise<SentimentResult[]> {
    return texts.map(() => ({ label: 'neutral', score: 0 }));
  },
  async extractEntities(texts: string[]): Promise<NEREntity[][]> {
    return texts.map(() => []);
  },
  async embedTexts(texts: string[]): Promise<number[][]> {
    return texts.map(() => []);
  },
  async summarize(texts: string[]): Promise<string[]> {
    return texts.map(() => '');
  },
};

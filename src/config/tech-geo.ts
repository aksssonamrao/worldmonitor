export interface StartupHub { id: string; name: string; city: string; country: string; lat: number; lon: number; ecosystemTier?: string; notableStartups?: string[]; keyProducts?: string[]; }
export interface Accelerator { id: string; name: string; city: string; country: string; lat: number; lon: number; type?: string; notable?: string[]; }
export interface TechHQ { id: string; company: string; city: string; country: string; lat: number; lon: number; type?: string; }
export interface CloudRegion { id: string; name: string; city: string; country: string; lat: number; lon: number; provider?: string; }

export const STARTUP_HUBS: StartupHub[] = [];
export const ACCELERATORS: Accelerator[] = [];
export const TECH_HQS: TechHQ[] = [];
export const CLOUD_REGIONS: CloudRegion[] = [];

import { createContext } from 'react';

import type { CacheStatsResponse } from '../types';

export interface CacheControlData {
  appliedThreshold: number;
  cacheStats: CacheStatsResponse;
}

export type CacheControlReadState =
  | { status: 'loading' }
  | { status: 'ready'; data: CacheControlData }
  | { status: 'error'; error: string };

export interface CacheControlContextValue {
  cacheState: CacheControlReadState;
  clearControlError: () => void;
  commitThreshold: (value: number) => Promise<void>;
  controlError: string | null;
  isApplyingThreshold: boolean;
  isRefreshingCacheState: boolean;
  previewThreshold: number | null;
  refreshCacheState: (syncPreview?: boolean) => Promise<void>;
  setPreviewThreshold: (value: number) => void;
}

export const CacheControlContext = createContext<CacheControlContextValue | null>(null);

import { useContext } from 'react';

import {
  CacheControlContext,
  type CacheControlContextValue,
} from '../context/cacheControlState';

export function useCacheControl(): CacheControlContextValue {
  const context = useContext(CacheControlContext);

  if (context === null) {
    throw new Error('useCacheControl must be used within a CacheControlProvider');
  }

  return context;
}

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type JSX,
} from 'react';

import {
  getCacheStats,
  getCacheThreshold,
  updateCacheThreshold,
} from '../api/cacheApi';
import { CacheControlContext, type CacheControlReadState } from './cacheControlState';

interface CacheControlProviderProps {
  children: ReactNode;
}

export function CacheControlProvider({
  children,
}: Readonly<CacheControlProviderProps>): JSX.Element {
  const [cacheState, setCacheState] = useState<CacheControlReadState>({
    status: 'loading',
  });
  const [previewThreshold, setPreviewThreshold] = useState<number | null>(null);
  const [isRefreshingCacheState, setIsRefreshingCacheState] = useState(false);
  const [controlError, setControlError] = useState<string | null>(null);
  const [isApplyingThreshold, setIsApplyingThreshold] = useState(false);
  const activeRefresh = useRef<AbortController | null>(null);
  const hasConfirmedState = useRef(false);
  const isApplying = useRef(false);
  const mounted = useRef(true);
  const refreshSequence = useRef(0);
  const writeSequence = useRef(0);

  const refreshCacheState = useCallback(async (syncPreview = false): Promise<void> => {
    if (isApplying.current) {
      return;
    }

    const controller = new AbortController();
    const requestId = refreshSequence.current + 1;
    refreshSequence.current = requestId;
    activeRefresh.current?.abort();
    activeRefresh.current = controller;

    if (hasConfirmedState.current) {
      setIsRefreshingCacheState(true);
    } else {
      setCacheState({ status: 'loading' });
      setIsRefreshingCacheState(false);
    }

    const [statsResult, thresholdResult] = await Promise.all([
      getCacheStats(controller.signal),
      getCacheThreshold(controller.signal),
    ]);

    if (
      controller.signal.aborted ||
      requestId !== refreshSequence.current ||
      !mounted.current
    ) {
      return;
    }

    activeRefresh.current = null;
    setIsRefreshingCacheState(false);
    const shouldSyncPreview = syncPreview || !hasConfirmedState.current;

    if (!statsResult.ok) {
      setCacheState({
        status: 'error',
        error:
          statsResult.error.detail ??
          'Cache statistics and threshold could not be loaded.',
      });
      return;
    }

    if (!thresholdResult.ok) {
      setCacheState({
        status: 'error',
        error:
          thresholdResult.error.detail ??
          'Cache statistics and threshold could not be loaded.',
      });
      return;
    }

    hasConfirmedState.current = true;
    setCacheState({
      status: 'ready',
      data: {
        appliedThreshold: thresholdResult.data.threshold,
        cacheStats: statsResult.data,
      },
    });
    if (shouldSyncPreview) {
      setPreviewThreshold(thresholdResult.data.threshold);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void refreshCacheState(true);

    return () => {
      mounted.current = false;
      refreshSequence.current += 1;
      writeSequence.current += 1;
      activeRefresh.current?.abort();
      activeRefresh.current = null;
    };
  }, [refreshCacheState]);

  const clearControlError = useCallback((): void => {
    setControlError(null);
  }, []);

  const commitThreshold = useCallback(
    async (value: number): Promise<void> => {
      const writeId = writeSequence.current + 1;
      writeSequence.current = writeId;
      refreshSequence.current += 1;
      activeRefresh.current?.abort();
      activeRefresh.current = null;
      isApplying.current = true;
      setIsRefreshingCacheState(false);
      setIsApplyingThreshold(true);

      try {
        const result = await updateCacheThreshold(value);
        if (writeId !== writeSequence.current || !mounted.current) {
          return;
        }

        if (result.ok) {
          hasConfirmedState.current = true;
          setCacheState((current) =>
            current.status === 'ready'
              ? {
                  status: 'ready',
                  data: {
                    ...current.data,
                    appliedThreshold: result.data.threshold,
                  },
                }
              : current,
          );
          setPreviewThreshold(result.data.threshold);
          setControlError(null);
          return;
        }

        isApplying.current = false;
        await refreshCacheState(true);
        if (writeId === writeSequence.current && mounted.current) {
          setControlError('THRESHOLD UPDATE FAILED; THE SERVER VALUE WAS RESTORED');
        }
      } finally {
        if (writeId === writeSequence.current && mounted.current) {
          isApplying.current = false;
          setIsApplyingThreshold(false);
        }
      }
    },
    [refreshCacheState],
  );

  const contextValue = useMemo(
    () => ({
      cacheState,
      clearControlError,
      commitThreshold,
      controlError,
      isApplyingThreshold,
      isRefreshingCacheState,
      previewThreshold,
      refreshCacheState,
      setPreviewThreshold,
    }),
    [
      cacheState,
      clearControlError,
      commitThreshold,
      controlError,
      isApplyingThreshold,
      isRefreshingCacheState,
      previewThreshold,
      refreshCacheState,
    ],
  );

  return (
    <CacheControlContext.Provider value={contextValue}>
      {children}
    </CacheControlContext.Provider>
  );
}

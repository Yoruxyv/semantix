import {
  useCallback,
  useMemo,
  useState,
  type ReactNode,
  type JSX,
} from "react";

import { MonitorContext } from "./monitorState";
import { useCacheControl } from "@/features/cache/hooks/useCacheControl";
import { useQuery } from "../hooks/useQuery";
import type {
  QueryEvidence,
  QuerySubmission,
  QueryTrace,
} from "../types";

const MAX_TRACES = 40;

interface MonitorProviderProps {
  children: ReactNode;
}

export function MonitorProvider({
  children,
}: Readonly<MonitorProviderProps>): JSX.Element {
  const { refreshCacheState } = useCacheControl();
  const { state: queryState, submit } = useQuery();
  const [traces, setTraces] = useState<QueryTrace[]>([]);
  const [latestEvidence, setLatestEvidence] =
    useState<QueryEvidence | null>(null);
  const submitPrompt = useCallback(
    async (submission: QuerySubmission): Promise<void> => {
      const result = await submit(submission.request);
      if (result === null) {
        return;
      }

      const namespace = submission.request.namespace ?? "default";
      setLatestEvidence({
        namespace,
        policyMode: submission.policyMode,
      });
      if (submission.request.private !== true) {
        setTraces((current) =>
          [
            {
              id: crypto.randomUUID(),
              prompt: submission.request.prompt,
              similarity: result.similarity_score,
              latencyMs: result.latency_ms,
              recordedAt: new Date(),
              actualCacheHit: result.cache_hit,
              namespace,
              policyMode: submission.policyMode,
              providerCalled: result.provider_called,
            },
            ...current,
          ].slice(0, MAX_TRACES),
        );
      }
      await refreshCacheState(false);
    },
    [refreshCacheState, submit],
  );

  const clearTraces = useCallback((): void => {
    setTraces([]);
  }, []);

  const contextValue = useMemo(
    () => ({
      clearTraces,
      latestEvidence,
      queryState,
      submitPrompt,
      traces,
    }),
    [clearTraces, latestEvidence, queryState, submitPrompt, traces],
  );

  return (
    <MonitorContext.Provider value={contextValue}>
      {children}
    </MonitorContext.Provider>
  );
}

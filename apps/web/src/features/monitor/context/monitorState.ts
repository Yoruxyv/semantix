import { createContext } from 'react';

import type { QueryEvidence, QueryState, QuerySubmission, QueryTrace } from '../types';

export interface MonitorContextValue {
  clearTraces: () => void;
  latestEvidence: QueryEvidence | null;
  queryState: QueryState;
  submitPrompt: (submission: QuerySubmission) => Promise<void>;
  traces: QueryTrace[];
}

export const MonitorContext = createContext<MonitorContextValue | null>(null);

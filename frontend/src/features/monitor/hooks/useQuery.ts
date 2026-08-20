import { useCallback, useEffect, useRef, useState } from 'react';

import { submitQuery } from '../api/queryApi';
import type { QueryRequest, QueryResponse, QueryState } from '../types';

export interface UseQueryResult {
  state: QueryState;
  submit: (request: QueryRequest) => Promise<QueryResponse | null>;
}

export function useQuery(): UseQueryResult {
  const [state, setState] = useState<QueryState>({ status: 'idle' });
  const controller = useRef<AbortController | null>(null);
  const requestId = useRef(0);

  useEffect(
    () => () => {
      requestId.current += 1;
      controller.current?.abort();
    },
    [],
  );

  const submit = useCallback(
    async (request: QueryRequest): Promise<QueryResponse | null> => {
      controller.current?.abort();
      controller.current = new AbortController();

      requestId.current += 1;
      const currentRequestId = requestId.current;

      setState({ status: 'loading' });

      const result = await submitQuery(request, controller.current.signal);

      if (currentRequestId !== requestId.current) {
        return null;
      }

      if (result.ok) {
        setState({
          status: 'success',
          data: result.data,
        });

        return result.data;
      }

      setState({
        status: 'error',
        error: result.error,
      });

      return null;
    },
    [],
  );

  return {
    state,
    submit,
  };
}

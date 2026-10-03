import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState, type JSX } from 'react';

import {
  deleteEvaluationRunHistory,
  getEvaluationRunHistory,
  getEvaluationRunHistoryDetail,
} from '@/features/benchmark/api/benchmarkApi';
import { useEvaluationRunComparison } from '@/features/benchmark/hooks/useEvaluationRunComparison';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { canDeleteEvaluationRunHistory } from '@/features/auth/permissions';
import { isCacheNamespace } from '@/features/cache/namespace';
import { Alert } from '@/shared/components/ui';
import { apiErrorFromUnknown, dataFromApiResult } from '@/shared/query/apiResult';
import { benchmarkHistoryKeys } from '@/shared/query/queryKeys';

import type { EvaluationRunHistoryItem } from '@/features/benchmark/types';
import { EvaluationRunComparisonWorkspace } from './EvaluationRunComparisonWorkspace';
import { EvaluationRunHistoryDetailPanel } from './EvaluationRunHistoryDetail';
import { EvaluationRunHistoryFilter } from './EvaluationRunHistoryFilter';
import { EvaluationRunHistoryList } from './EvaluationRunHistoryList';

const PAGE_SIZE = 12;

function defaultNamespace(
  status: ReturnType<typeof useAuth>['status'],
  namespaces: string[],
  hasGlobalNamespace: boolean,
): string {
  if (status === 'authenticated' && !hasGlobalNamespace) {
    return namespaces[0] ?? '';
  }
  return '';
}

export function EvaluationRunHistory(): JSX.Element {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const comparison = useEvaluationRunComparison();
  const namespaces = useMemo(
    () => auth.session?.namespaces.filter((item) => item !== '*') ?? [],
    [auth.session],
  );
  const hasGlobalNamespace = auth.session?.namespaces.includes('*') ?? false;
  const initialNamespace = defaultNamespace(
    auth.status,
    namespaces,
    hasGlobalNamespace,
  );

  const [namespaceInput, setNamespaceInput] = useState(initialNamespace);
  const [namespace, setNamespace] = useState(initialNamespace);
  const [namespaceError, setNamespaceError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [deletingRunId, setDeletingRunId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [statusMessage, setStatusMessage] = useState('');

  const resetComparison = comparison.clear;

  useEffect(() => {
    const nextNamespace = defaultNamespace(auth.status, namespaces, hasGlobalNamespace);
    setNamespaceInput(nextNamespace);
    setNamespace(nextNamespace);
    setOffset(0);
    setSelectedRunId(null);
    setPendingDelete(null);
    setNamespaceError(null);
    resetComparison();
  }, [
    auth.session?.name,
    auth.status,
    hasGlobalNamespace,
    namespaces,
    resetComparison,
  ]);

  const catalogQuery = useQuery({
    queryKey: benchmarkHistoryKeys.list(namespace, offset, PAGE_SIZE),
    queryFn: async ({ signal }) =>
      dataFromApiResult(
        await getEvaluationRunHistory(
          {
            ...(namespace === '' ? {} : { namespace }),
            offset,
            limit: PAGE_SIZE,
          },
          signal,
        ),
      ),
  });

  const detailQuery = useQuery({
    queryKey: benchmarkHistoryKeys.detail(selectedRunId ?? ''),
    queryFn: async ({ signal }) => {
      if (selectedRunId === null) {
        throw new Error('No retained evaluation run is selected.');
      }
      return dataFromApiResult(
        await getEvaluationRunHistoryDetail(selectedRunId, signal),
      );
    },
    enabled: selectedRunId !== null && catalogQuery.data?.retention_enabled === true,
  });

  const canDelete = canDeleteEvaluationRunHistory(auth.status, auth.session);

  function applyNamespace(): void {
    const trimmed = namespaceInput.trim();
    if (trimmed !== '' && !isCacheNamespace(trimmed)) {
      setNamespaceError('Enter a valid authorized namespace.');
      return;
    }
    setNamespaceError(null);
    setNamespace(trimmed);
    setOffset(0);
    setSelectedRunId(null);
    setPendingDelete(null);
    comparison.clear();
  }

  async function deleteRun(item: EvaluationRunHistoryItem): Promise<void> {
    setDeletingRunId(item.run_id);
    setActionError(null);
    try {
      const response = await deleteEvaluationRunHistory(item.run_id, item.namespace);
      if (!response.ok) {
        setActionError(
          response.error.detail ?? 'The retained run could not be deleted.',
        );
        return;
      }

      setPendingDelete(null);
      if (selectedRunId === item.run_id) {
        setSelectedRunId(null);
      }
      comparison.removeRun(item.run_id);
      await queryClient.invalidateQueries({
        queryKey: benchmarkHistoryKeys.all,
      });
      setStatusMessage(
        `Deleted retained run ${item.run_id.slice(0, 12)} from ${item.namespace}.`,
      );
    } finally {
      setDeletingRunId(null);
    }
  }

  const catalog = catalogQuery.data;
  const catalogError = catalogQuery.isError
    ? (apiErrorFromUnknown(catalogQuery.error).detail ??
      'Evaluation run history could not be loaded.')
    : null;
  const detailError = detailQuery.isError
    ? (apiErrorFromUnknown(detailQuery.error).detail ??
      'The retained run detail could not be loaded.')
    : null;

  return (
    <section aria-labelledby="run-history-heading" className="mt-6">
      <header className="border-y border-(--hairline) py-5">
        <p className="ui-label text-(--gold)">Durable evaluation evidence</p>
        <h2
          className="font-display mt-2 text-2xl italic text-(--text)"
          id="run-history-heading"
        >
          Run history
        </h2>
        <p className="mt-2 max-w-3xl text-sm/6 text-(--text-muted)">
          Browse terminal aggregate results retained by namespace. Select exactly two
          retained runs for a server-checked comparison. History never stores per-query
          prompts, generated responses, or matched cache keys.
        </p>
      </header>

      <EvaluationRunHistoryFilter
        authStatus={auth.status}
        hasGlobalNamespace={hasGlobalNamespace}
        namespace={namespace}
        namespaceError={namespaceError}
        namespaceInput={namespaceInput}
        namespaces={namespaces}
        onApplyNamespace={applyNamespace}
        onNamespaceInputChange={setNamespaceInput}
        onScopedNamespaceChange={(value) => {
          setNamespaceInput(value);
          setNamespace(value);
          setOffset(0);
          setSelectedRunId(null);
          comparison.clear();
        }}
      />

      {catalogQuery.isPending && (
        <output
          aria-live="polite"
          className="font-data mt-5 block text-[10px]/5 text-(--text-muted)"
        >
          Loading retained evaluation runs...
        </output>
      )}

      {catalogError !== null && (
        <Alert className="mt-5" role="alert" title="History unavailable" tone="error">
          <p className="font-data mt-1 text-[10px]/5 text-(--text-soft)">
            {catalogError}
          </p>
        </Alert>
      )}

      {catalog?.retention_enabled === false && (
        <Alert
          className="mt-5 border-l-2 border-(--gold) px-4 py-3"
          title="Durable history is disabled"
          tone="warning"
        >
          <p className="font-data mt-1 text-[10px]/5 text-(--text-soft)">
            This deployment does not retain evaluation runs in PostgreSQL. Measured runs
            can still complete normally, but no durable history is available to browse
            or compare.
          </p>
        </Alert>
      )}

      {actionError !== null && (
        <Alert className="mt-5" role="alert" title="History action failed" tone="error">
          <p className="font-data mt-1 text-[10px]/5 text-(--text-soft)">
            {actionError}
          </p>
        </Alert>
      )}

      {statusMessage !== '' && (
        <output
          aria-live="polite"
          className="font-data mt-4 block text-[10px]/5 text-(--teal)"
        >
          {statusMessage}
        </output>
      )}

      {catalog?.retention_enabled === true && (
        <EvaluationRunHistoryList
          canDelete={canDelete}
          catalog={catalog}
          comparisonRunIds={comparison.selectedRuns.map((item) => item.run_id)}
          deletingRunId={deletingRunId}
          offset={offset}
          pendingDelete={pendingDelete}
          onDelete={(item) => void deleteRun(item)}
          onDeleteCancel={() => setPendingDelete(null)}
          onDeleteRequest={(runId) => {
            setActionError(null);
            setPendingDelete(runId);
          }}
          onOffsetChange={(nextOffset) => {
            setOffset(nextOffset);
            setSelectedRunId(null);
          }}
          onSelect={(runId) => {
            setActionError(null);
            setSelectedRunId(runId);
          }}
          onToggleComparison={comparison.toggleRun}
        />
      )}

      <EvaluationRunComparisonWorkspace controller={comparison} />

      {detailQuery.isPending && selectedRunId !== null && (
        <output
          aria-live="polite"
          className="font-data mt-5 block text-[10px]/5 text-(--text-muted)"
        >
          Loading retained run detail...
        </output>
      )}

      {detailError !== null && (
        <Alert
          className="mt-5"
          role="alert"
          title="Run detail unavailable"
          tone="error"
        >
          <p className="font-data mt-1 text-[10px]/5 text-(--text-soft)">
            {detailError}
          </p>
        </Alert>
      )}

      {detailQuery.data !== undefined && (
        <EvaluationRunHistoryDetailPanel
          detail={detailQuery.data}
          onClose={() => setSelectedRunId(null)}
        />
      )}
    </section>
  );
}

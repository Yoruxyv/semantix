import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState, type JSX } from 'react';

import {
  canDeleteEvaluationDatasets,
  canRunBenchmarks,
} from '@/features/auth/permissions';
import { useAuth } from '@/features/auth/hooks/useAuth';
import { isCacheNamespace } from '@/features/cache/namespace';
import { Alert } from '@/shared/components/ui';
import { apiErrorFromUnknown, dataFromApiResult } from '@/shared/query/apiResult';
import { benchmarkDatasetKeys } from '@/shared/query/queryKeys';
import {
  deletePersistedEvaluationDataset,
  getPersistedEvaluationDataset,
  getPersistedEvaluationDatasets,
} from '@/features/benchmark/api/benchmarkApi';
import type { BenchmarkController } from '@/features/benchmark/hooks/useBenchmark';
import type { PersistedEvaluationDatasetMetadata } from '@/features/benchmark/types';

import { EvaluationDatasetSavePanel } from './EvaluationDatasetSavePanel';
import { EvaluationDatasetSourceSummary } from './EvaluationDatasetSourceSummary';
import { PersistedEvaluationDatasetDetail } from './PersistedEvaluationDatasetDetail';
import { PersistedEvaluationDatasetList } from './PersistedEvaluationDatasetList';
import {
  EVALUATION_DATASET_PAGE_SIZE,
  defaultListNamespace,
  defaultSaveNamespace,
} from './datasetCatalogShared';

interface EvaluationDatasetCatalogProps {
  controller: BenchmarkController;
  onUseDataset: () => void;
}

export function EvaluationDatasetCatalog({
  controller,
  onUseDataset,
}: Readonly<EvaluationDatasetCatalogProps>): JSX.Element {
  const auth = useAuth();
  const queryClient = useQueryClient();
  const namespaces = useMemo(
    () => auth.session?.namespaces.filter((item) => item !== '*') ?? [],
    [auth.session],
  );
  const hasGlobalNamespace = auth.session?.namespaces.includes('*') ?? false;
  const [listNamespace, setListNamespace] = useState(
    defaultListNamespace(auth.status, namespaces, hasGlobalNamespace),
  );
  const [saveNamespace, setSaveNamespace] = useState(
    defaultSaveNamespace(auth.status, namespaces),
  );
  const [retentionDays, setRetentionDays] = useState(30);
  const [offset, setOffset] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [catalogStatus, setCatalogStatus] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    setSaveNamespace(defaultSaveNamespace(auth.status, namespaces));
    setListNamespace(defaultListNamespace(auth.status, namespaces, hasGlobalNamespace));
    setOffset(0);
    setSelectedId(null);
    setPendingDelete(null);
  }, [auth.status, auth.session?.name, hasGlobalNamespace, namespaces]);

  const catalogQuery = useQuery({
    queryKey: benchmarkDatasetKeys.persistedList(
      listNamespace,
      offset,
      EVALUATION_DATASET_PAGE_SIZE,
    ),
    queryFn: async ({ signal }) =>
      dataFromApiResult(
        await getPersistedEvaluationDatasets(
          {
            ...(listNamespace === '' ? {} : { namespace: listNamespace }),
            offset,
            limit: EVALUATION_DATASET_PAGE_SIZE,
          },
          signal,
        ),
      ),
  });
  const catalog = catalogQuery.data;

  const defaultRetentionDays = catalog?.limits.default_retention_days;
  useEffect(() => {
    if (defaultRetentionDays !== undefined) {
      setRetentionDays(defaultRetentionDays);
    }
  }, [defaultRetentionDays]);

  const detailQuery = useQuery({
    queryKey: benchmarkDatasetKeys.persistedDetail(selectedId ?? ''),
    queryFn: async ({ signal }) => {
      if (selectedId === null) {
        throw new Error('No persisted dataset is selected.');
      }
      return dataFromApiResult(await getPersistedEvaluationDataset(selectedId, signal));
    },
    enabled: selectedId !== null && catalog?.persistence_enabled === true,
  });

  const canDelete = canDeleteEvaluationDatasets(auth.status, auth.session);
  const canRun = canRunBenchmarks(auth.status, auth.session);
  const requiresSaveNamespace =
    auth.status === 'disabled' ||
    (auth.status === 'authenticated' && (hasGlobalNamespace || namespaces.length > 1));
  const saveNamespaceValid = !requiresSaveNamespace || isCacheNamespace(saveNamespace);

  async function saveSessionDataset(): Promise<void> {
    if (!saveNamespaceValid) {
      return;
    }
    setActionError(null);
    const saved = await controller.saveImport(saveNamespace, retentionDays);
    if (saved !== null) {
      setCatalogStatus(`Saved ${saved.name} in namespace ${saved.namespace}.`);
      setSelectedId(saved.dataset_id);
    }
  }

  async function deleteDataset(
    dataset: PersistedEvaluationDatasetMetadata,
  ): Promise<void> {
    setDeletingId(dataset.dataset_id);
    setActionError(null);
    try {
      const response = await deletePersistedEvaluationDataset(
        dataset.dataset_id,
        dataset.namespace,
      );
      if (!response.ok) {
        setActionError(
          response.error.detail ?? 'The persisted dataset could not be deleted.',
        );
        return;
      }
      setPendingDelete(null);
      if (selectedId === dataset.dataset_id) {
        setSelectedId(null);
      }
      controller.clearPersistedSelection(dataset.dataset_id);
      await queryClient.invalidateQueries({
        queryKey: benchmarkDatasetKeys.persisted(),
      });
      setCatalogStatus(`Deleted ${dataset.name} from namespace ${dataset.namespace}.`);
    } finally {
      setDeletingId(null);
    }
  }

  function useSelectedDataset(): void {
    if (detailQuery.data === undefined) {
      return;
    }
    controller.selectPersistedDataset(detailQuery.data);
    onUseDataset();
  }

  const catalogError = catalogQuery.isError
    ? (apiErrorFromUnknown(catalogQuery.error).detail ??
      'The persisted dataset catalog could not be loaded.')
    : null;
  const detailError = detailQuery.isError
    ? (apiErrorFromUnknown(detailQuery.error).detail ??
      'The persisted dataset details could not be loaded.')
    : null;

  return (
    <section aria-labelledby="dataset-catalog-heading" className="mt-6">
      <header className="border-y border-(--hairline) py-5">
        <p className="ui-label text-(--gold)">Dataset sources</p>
        <h2
          className="font-display mt-2 text-2xl italic text-(--text)"
          id="dataset-catalog-heading"
        >
          Evaluation datasets
        </h2>
        <p className="mt-2 max-w-3xl text-sm/6 text-(--text-muted)">
          Built-in definitions stay code-owned. Session imports remain only in this page
          until an Operator explicitly saves a validated dataset to an authorized
          namespace.
        </p>
      </header>

      <EvaluationDatasetSourceSummary controller={controller} />

      {catalog?.persistence_enabled === false && (
        <Alert
          className="mt-6 border-l-2 border-(--gold) px-4 py-3"
          title="Persistence is disabled"
          tone="warning"
        >
          <p className="font-data mt-1 text-[10px]/5 text-(--text-soft)">
            This deployment uses session-only evaluation datasets. Built-in and imported
            runs still work, but validated imports cannot be saved across reloads.
          </p>
        </Alert>
      )}

      {catalog?.persistence_enabled === true &&
        controller.canSaveImport &&
        controller.preview !== null && (
          <EvaluationDatasetSavePanel
            authStatus={auth.status}
            hasGlobalNamespace={hasGlobalNamespace}
            isSaving={controller.isSavingImport}
            maxRetentionDays={catalog.limits.max_retention_days}
            namespaces={namespaces}
            retentionDays={retentionDays}
            saveNamespace={saveNamespace}
            saveNamespaceValid={saveNamespaceValid}
            setRetentionDays={setRetentionDays}
            setSaveNamespace={setSaveNamespace}
            onSave={() => void saveSessionDataset()}
          />
        )}

      {catalog?.persistence_enabled === true && (
        <PersistedEvaluationDatasetList
          canDelete={canDelete}
          catalog={catalog}
          deletingId={deletingId}
          hasGlobalNamespace={hasGlobalNamespace}
          listNamespace={listNamespace}
          namespaces={namespaces}
          offset={offset}
          pendingDelete={pendingDelete}
          onDelete={(dataset) => void deleteDataset(dataset)}
          onDeleteCancel={() => setPendingDelete(null)}
          onDeleteRequest={setPendingDelete}
          onNamespaceChange={(namespace) => {
            setListNamespace(namespace);
            setOffset(0);
          }}
          onOffsetChange={setOffset}
          onSelect={(datasetId) => {
            setSelectedId(datasetId);
            setActionError(null);
          }}
        />
      )}

      {selectedId !== null && catalog?.persistence_enabled === true && (
        <PersistedEvaluationDatasetDetail
          canRun={canRun}
          detail={detailQuery.data}
          isPending={detailQuery.isPending}
          onUseDataset={useSelectedDataset}
        />
      )}

      {(catalogError !== null || detailError !== null || actionError !== null) && (
        <Alert
          className="mt-6 border-l-2 border-(--coral) px-4 py-3"
          role="alert"
          title="Dataset catalog error"
          tone="error"
        >
          <p className="font-data mt-1 text-[10px]/5 text-(--text-soft)">
            {actionError ?? detailError ?? catalogError}
          </p>
        </Alert>
      )}

      {(catalogQuery.isPending || catalogQuery.isFetching) && (
        <output
          aria-live="polite"
          className="font-data mt-4 block text-[10px]/5 text-(--text-muted)"
        >
          {catalogQuery.isPending
            ? 'Loading persisted dataset catalog...'
            : 'Refreshing persisted dataset catalog...'}
        </output>
      )}
      {catalogStatus !== '' && (
        <output
          aria-live="polite"
          className="font-data mt-4 block text-[10px]/5 text-(--teal)"
        >
          {catalogStatus}
        </output>
      )}
    </section>
  );
}

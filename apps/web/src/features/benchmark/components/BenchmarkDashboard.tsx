import { useState, type JSX } from 'react';

import { Alert, Button, EmptyState, PageHeader } from '@/shared/components/ui';
import { useBenchmark } from '../hooks/useBenchmark';
import { BenchmarkAnalysis } from './results/BenchmarkAnalysis';
import { BenchmarkCharts } from './charts/BenchmarkCharts';
import { BenchmarkControls } from './run/BenchmarkControls';
import { BenchmarkDatasetSkeleton } from './datasets/BenchmarkDatasetSkeleton';
import { BenchmarkExports } from './exports/BenchmarkExports';
import { BenchmarkResultsSkeleton } from './results/BenchmarkResultsSkeleton';
import { BenchmarkRunWarning } from './run/BenchmarkRunWarning';
import { BenchmarkSummary } from './results/BenchmarkSummary';
import { EvaluationDatasetCatalog } from './datasets/EvaluationDatasetCatalog';
import { EvaluationRunHistory } from './history/EvaluationRunHistory';

export function BenchmarkDashboard(): JSX.Element {
  const controller = useBenchmark();
  const [view, setView] = useState<'runs' | 'datasets' | 'history'>('runs');
  const {
    datasetsLoading,
    datasetsRefreshing,
    error,
    isRunning,
    result,
    selectedDataset,
    showWarning,
  } = controller;

  let viewContent: JSX.Element;

  if (view === 'datasets') {
    viewContent = (
      <EvaluationDatasetCatalog
        controller={controller}
        onUseDataset={() => setView('runs')}
      />
    );
  } else if (view === 'history') {
    viewContent = <EvaluationRunHistory />;
  } else {
    viewContent = (
      <>
        {datasetsLoading ? (
          <BenchmarkDatasetSkeleton />
        ) : (
          <BenchmarkControls controller={controller} />
        )}

        {datasetsRefreshing && (
          <output aria-live="polite" className="ui-label mt-3 block text-(--gold)">
            Refreshing dataset catalog
          </output>
        )}

        {selectedDataset !== null && (
          <p className="font-data mt-3 text-[10px]/5 text-(--text-faint)">
            {selectedDataset.description} Dataset version {selectedDataset.version} -
            digest {selectedDataset.digest.slice(0, 12)}...
          </p>
        )}

        <BenchmarkRunWarning controller={controller} />

        {controller.statusMessage !== '' && (
          <output
            aria-live="polite"
            className="font-data mt-4 block text-[10px]/5 text-(--text-muted)"
          >
            {controller.statusMessage}
          </output>
        )}

        {isRunning && <BenchmarkResultsSkeleton />}

        {error !== null && (
          <Alert
            className="mt-6 border-l-2 border-(--coral) bg-[rgba(194,96,74,0.06)] px-4 py-3"
            role="alert"
            title="Evaluation failed"
            tone="error"
          >
            <p className="font-data mt-1 text-[11px]/5 text-(--text-soft)">{error}</p>
          </Alert>
        )}

        {!datasetsLoading &&
          result === null &&
          !isRunning &&
          !showWarning &&
          error === null && (
            <EmptyState
              className="mt-8 py-6"
              description="Review the selected dataset and threshold before starting a controlled run. Results remain in this browser session and are discarded on reload."
              title="No measured run yet"
            />
          )}

        {result !== null && (
          <>
            <BenchmarkSummary result={result} />
            <BenchmarkCharts result={result} />
            <BenchmarkAnalysis key={result.run_id} result={result} />
          </>
        )}
      </>
    );
  }

  return (
    <section aria-labelledby="evaluation-heading" className="pb-4">
      <PageHeader
        actions={
          view === 'runs' && result !== null ? (
            <BenchmarkExports result={result} />
          ) : undefined
        }
        className="mb-7"
        description="Measure cache quality, latency, provider savings, and threshold trade-offs against prompts with explicit expected decisions."
        eyebrow="Controlled evaluation"
        headingId="evaluation-heading"
        title="Evaluation laboratory"
      />

      <nav
        aria-label="Evaluation laboratory views"
        className="mb-6 flex flex-wrap gap-3 border-b border-(--hairline) pb-4"
      >
        <Button
          aria-pressed={view === 'runs'}
          size="compact"
          variant={view === 'runs' ? 'primary' : 'secondary'}
          onClick={() => setView('runs')}
        >
          Runs
        </Button>
        <Button
          aria-pressed={view === 'datasets'}
          size="compact"
          variant={view === 'datasets' ? 'primary' : 'secondary'}
          onClick={() => setView('datasets')}
        >
          Datasets
        </Button>
        <Button
          aria-pressed={view === 'history'}
          size="compact"
          variant={view === 'history' ? 'primary' : 'secondary'}
          onClick={() => setView('history')}
        >
          History
        </Button>
      </nav>

      {viewContent}
    </section>
  );
}

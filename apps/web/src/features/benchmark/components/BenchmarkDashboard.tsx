import type { JSX } from 'react';
import { Link, useLocation, useNavigate } from 'react-router';

import { Alert, EmptyState, PageHeader } from '@/shared/components/ui';
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
import { ReuseQuality } from '../quality/ReuseQuality';

const EVALUATION_VIEWS = [
  { key: 'runs', label: 'Runs' },
  { key: 'datasets', label: 'Datasets' },
  { key: 'history', label: 'History' },
  { key: 'reuse-quality', label: 'Reuse quality' },
] as const;
type EvaluationView = (typeof EVALUATION_VIEWS)[number]['key'];

/**
 * Compose URL-selected panels around one controller; panel changes can unmount children.
 * Run-keyed analysis resets local filters/details when a different result is displayed.
 */
export function BenchmarkDashboard(): JSX.Element {
  const controller = useBenchmark();
  const { pathname, search, hash } = useLocation();
  const navigate = useNavigate();
  const requestedView = new URLSearchParams(search).get('view');
  const view =
    EVALUATION_VIEWS.find((item) => item.key === requestedView)?.key ?? 'runs';

  function viewLocation(next: EvaluationView) {
    const params = new URLSearchParams(search);
    params.set('view', next);
    return { pathname, search: `?${params.toString()}`, hash };
  }
  const { datasetsLoading, error, isRunning, result, selectedDataset, showWarning } =
    controller;

  let viewContent: JSX.Element;

  if (view === 'reuse-quality') {
    viewContent = <ReuseQuality />;
  } else if (view === 'datasets') {
    viewContent = (
      <EvaluationDatasetCatalog
        controller={controller}
        onUseDataset={() => void navigate(viewLocation('runs'))}
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
        description="Run isolated, ordered server evaluations or inspect reviewed static library evidence. These describe different workflows; neither establishes a universally safe reuse threshold."
        eyebrow="Evaluations and reviewed evidence"
        headingId="evaluation-heading"
        title="Evaluation laboratory"
      />

      <nav
        aria-label="Evaluation laboratory views"
        className="mb-6 flex flex-wrap gap-3 border-b border-(--hairline) pb-4"
      >
        {EVALUATION_VIEWS.map((item) => (
          <Link
            key={item.key}
            aria-current={view === item.key ? 'page' : undefined}
            className={`ui-label inline-flex min-h-11 items-center border px-3 py-2 transition-colors focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-(--gold) ${
              view === item.key
                ? 'border-(--gold) bg-(--gold) text-(--ink)'
                : 'border-(--hairline) text-(--text-muted) hover:border-(--gold) hover:text-(--gold)'
            }`}
            to={viewLocation(item.key)}
          >
            {item.label}
          </Link>
        ))}
      </nav>

      {viewContent}
    </section>
  );
}

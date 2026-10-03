import type { JSX } from 'react';

import { Button } from '@/shared/components/ui';

import type { PersistedEvaluationDatasetDetail as PersistedDatasetDetail } from '@/features/benchmark/types';
import { EvaluationDatasetMetadata } from './EvaluationDatasetMetadata';

interface PersistedEvaluationDatasetDetailProps {
  canRun: boolean;
  detail: PersistedDatasetDetail | undefined;
  isPending: boolean;
  onUseDataset: () => void;
}

export function PersistedEvaluationDatasetDetail({
  canRun,
  detail,
  isPending,
  onUseDataset,
}: Readonly<PersistedEvaluationDatasetDetailProps>): JSX.Element {
  return (
    <section
      aria-labelledby="persisted-dataset-detail-heading"
      className="mt-7 border-y border-(--hairline) py-6"
    >
      <h3 className="ui-label text-(--gold)" id="persisted-dataset-detail-heading">
        Persisted dataset detail
      </h3>
      {isPending && (
        <output
          aria-live="polite"
          className="font-data mt-3 block text-[10px]/5 text-(--text-muted)"
        >
          Loading dataset details...
        </output>
      )}
      {detail !== undefined && (
        <>
          <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <h4 className="wrap-break-word text-xl text-(--text)">{detail.name}</h4>
              <EvaluationDatasetMetadata dataset={detail} />
            </div>
            {canRun && (
              <Button variant="primary" onClick={onUseDataset}>
                Use for benchmark
              </Button>
            )}
          </div>
          <ol className="mt-5 grid gap-3">
            {detail.cases.map((item, index) => (
              <li
                key={item.case_id}
                className="min-w-0 border-l border-(--hairline) pl-4"
              >
                <p className="ui-label wrap-break-word text-(--text-muted)">
                  {index + 1}. {item.case_id}
                </p>
                <p className="mt-2 whitespace-pre-wrap wrap-break-word text-sm/6 text-(--text-soft)">
                  {item.prompt}
                </p>
                <p className="font-data mt-2 wrap-break-word text-[10px]/5 text-(--text-faint)">
                  Expected {item.expected_cache_hit ? 'HIT' : 'MISS'} ·{' '}
                  {item.category ?? 'uncategorized'}
                  {item.expected_match_case_id === null
                    ? ''
                    : ` · match ${item.expected_match_case_id}`}
                </p>
                {item.note !== null && (
                  <p className="font-data mt-1 whitespace-pre-wrap wrap-break-word text-[10px]/5 text-(--text-muted)">
                    {item.note}
                  </p>
                )}
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}

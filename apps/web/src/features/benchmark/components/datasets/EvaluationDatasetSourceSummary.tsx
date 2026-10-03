import type { JSX } from 'react';

import { formatBytes, formatCount } from '@/shared/lib/formatters';

import type { BenchmarkController } from '@/features/benchmark/hooks/useBenchmark';
import { EvaluationDatasetDigest } from './EvaluationDatasetMetadata';

interface EvaluationDatasetSourceSummaryProps {
  controller: BenchmarkController;
}

export function EvaluationDatasetSourceSummary({
  controller,
}: Readonly<EvaluationDatasetSourceSummaryProps>): JSX.Element {
  return (
    <section aria-labelledby="dataset-source-summary" className="mt-6">
      <h3 className="ui-label text-(--text-muted)" id="dataset-source-summary">
        Built-in and session sources
      </h3>
      <div className="mt-3 grid gap-4 lg:grid-cols-2">
        <article className="border border-(--hairline) p-4">
          <p className="ui-label text-(--teal)">Built-in</p>
          <p className="font-data mt-2 text-xs text-(--text-soft)">
            {controller.datasets.map((item) => item.name).join(', ')}
          </p>
          <p className="font-data mt-2 text-[10px]/5 text-(--text-faint)">
            Shipped with Semantix; not stored in the dataset catalog.
          </p>
        </article>
        <article className="border border-(--hairline) p-4">
          <p className="ui-label text-(--gold)">Session</p>
          {controller.preview === null ? (
            <p className="font-data mt-2 text-[10px]/5 text-(--text-faint)">
              No validated session import. Return to Runs to choose and validate a
              schema version 1 JSON file.
            </p>
          ) : (
            <>
              <h4 className="mt-2 wrap-break-word text-base text-(--text)">
                {controller.preview.name}
              </h4>
              <p className="font-data mt-2 text-[10px]/5 text-(--text-muted)">
                {formatCount(controller.preview.case_count)} cases ·{' '}
                {formatBytes(controller.preview.decoded_bytes)} ·{' '}
                <EvaluationDatasetDigest value={controller.preview.digest} />
              </p>
            </>
          )}
        </article>
      </div>
    </section>
  );
}

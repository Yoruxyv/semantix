import type { JSX } from 'react';

import { formatBytes, formatCount, formatTimestamp } from '@/shared/lib/formatters';

import type { PersistedEvaluationDatasetMetadata } from '@/features/benchmark/types';

function Digest({ value }: Readonly<{ value: string }>): JSX.Element {
  return (
    <code
      aria-label={`SHA-256 digest ${value}`}
      className="font-data text-[10px] text-(--text-faint)"
      title={value}
    >
      {value.slice(0, 12)}...
    </code>
  );
}

export function EvaluationDatasetMetadata({
  dataset,
}: Readonly<{
  dataset: PersistedEvaluationDatasetMetadata;
}>): JSX.Element {
  return (
    <dl className="font-data mt-4 grid grid-cols-2 gap-x-5 gap-y-3 text-[10px]/5">
      <div className="min-w-0">
        <dt className="text-(--text-faint)">Namespace</dt>
        <dd
          className="mt-1 wrap-break-word text-(--text-soft)"
          title={dataset.namespace}
        >
          {dataset.namespace}
        </dd>
      </div>
      <div>
        <dt className="text-(--text-faint)">Schema / digest</dt>
        <dd className="mt-1 text-(--text-soft)">
          v{dataset.schema_version} · <Digest value={dataset.digest} />
        </dd>
      </div>
      <div>
        <dt className="text-(--text-faint)">Cases / content</dt>
        <dd className="mt-1 text-(--text-soft)">
          {formatCount(dataset.case_count)} · {formatBytes(dataset.decoded_bytes)}
        </dd>
      </div>
      <div>
        <dt className="text-(--text-faint)">Created</dt>
        <dd
          className="mt-1 wrap-break-word text-(--text-soft)"
          title={dataset.created_at}
        >
          {formatTimestamp(dataset.created_at)}
        </dd>
      </div>
      <div className="col-span-2">
        <dt className="text-(--text-faint)">Expires</dt>
        <dd className="mt-1 wrap-break-word text-(--gold)" title={dataset.expires_at}>
          {formatTimestamp(dataset.expires_at)}
        </dd>
      </div>
    </dl>
  );
}

export function EvaluationDatasetDigest({
  value,
}: Readonly<{ value: string }>): JSX.Element {
  return <Digest value={value} />;
}

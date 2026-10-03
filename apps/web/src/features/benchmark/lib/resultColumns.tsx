import type { ReactNode } from 'react';

import { formatCount, formatLatency, formatSimilarity } from '@/shared/lib/formatters';
import { cacheDecisionLabel } from '@/shared/domain/similarity';
import type { BenchmarkQueryResult } from '../types';

export interface BenchmarkResultColumn {
  cellClassName: string | ((result: BenchmarkQueryResult) => string);
  header: string;
  headerClassName?: string;
  id: string;
  render: (result: BenchmarkQueryResult) => ReactNode;
}

function formatLabel(value: string): string {
  return value.replaceAll('_', ' ');
}

export const BENCHMARK_RESULT_COLUMNS: readonly BenchmarkResultColumn[] = [
  {
    cellClassName: 'px-3 py-4 text-(--text-faint)',
    header: 'Sequence',
    id: 'sequence',
    render: (result) => formatCount(result.sequence),
  },
  {
    cellClassName: 'px-3 py-4 text-(--text-muted)',
    header: 'Repetition',
    id: 'repetition',
    render: (result) => formatCount(result.repetition),
  },
  {
    cellClassName: 'max-w-40 break-words px-3 py-4 text-(--text-soft)',
    header: 'Case ID',
    id: 'case-id',
    render: (result) => result.case_id,
  },
  {
    cellClassName: 'px-3 py-4 capitalize text-(--text-muted)',
    header: 'Category',
    id: 'category',
    render: (result) => formatLabel(result.category),
  },
  {
    cellClassName: 'max-w-md px-3 py-4 leading-5 text-(--text-soft)',
    header: 'Query',
    id: 'query',
    render: (result) => result.prompt,
  },
  {
    cellClassName: 'px-3 py-4 text-(--text-muted)',
    header: 'Expected',
    id: 'expected',
    render: (result) => cacheDecisionLabel(result.expected_cache_hit),
  },
  {
    cellClassName: (result) =>
      result.actual_cache_hit
        ? 'px-3 py-4 text-(--teal)'
        : 'px-3 py-4 text-(--coral-text)',
    header: 'Actual',
    id: 'actual',
    render: (result) => cacheDecisionLabel(result.actual_cache_hit),
  },
  {
    cellClassName: 'px-3 py-4 tabular-nums',
    header: 'Score',
    id: 'score',
    render: (result) => formatSimilarity(result.similarity_score),
  },
  {
    cellClassName: 'px-3 py-4 tabular-nums',
    header: 'Latency',
    id: 'latency',
    render: (result) => formatLatency(result.latency_ms),
  },
  {
    cellClassName: (result) =>
      `px-3 py-4 capitalize ${
        result.correct ? 'text-(--teal)' : 'text-(--coral-text)'
      }`,
    header: 'Outcome',
    id: 'outcome',
    render: (result) => formatLabel(result.outcome),
  },
];

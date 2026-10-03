import type { BenchmarkQueryResult, BenchmarkRunResponse } from '../types';

type CsvValue = string | number | boolean | null;

interface CsvColumn {
  header: string;
  value: (result: BenchmarkRunResponse, query: BenchmarkQueryResult) => CsvValue;
}

const CSV_COLUMNS: readonly CsvColumn[] = [
  { header: 'export_schema_version', value: () => '3' },
  { header: 'run_id', value: (result) => result.run_id },
  { header: 'started_at', value: (result) => result.started_at },
  { header: 'completed_at', value: (result) => result.completed_at },
  { header: 'dataset_id', value: (result) => result.dataset.dataset_id },
  {
    header: 'dataset_source',
    value: (result) => result.dataset.dataset_source,
  },
  {
    header: 'dataset_schema_version',
    value: (result) => result.dataset.schema_version,
  },
  {
    header: 'dataset_version',
    value: (result) => result.dataset.version,
  },
  { header: 'dataset_digest', value: (result) => result.dataset.digest },
  {
    header: 'measured_threshold',
    value: (result) => result.reproducibility.measured_threshold,
  },
  {
    header: 'evaluation_thresholds',
    value: (result) => JSON.stringify(result.reproducibility.evaluation_thresholds),
  },
  {
    header: 'threshold_evaluation_mode',
    value: (result) => result.threshold_evaluation_mode,
  },
  {
    header: 'configuration_fingerprint',
    value: (result) => result.reproducibility.configuration_fingerprint,
  },
  { header: 'repetitions', value: (result) => result.repetitions },
  {
    header: 'reset_cache_before_run',
    value: (result) => result.reset_cache_before_run,
  },
  {
    header: 'application_version',
    value: (result) => result.reproducibility.application_version,
  },
  {
    header: 'embedding_provider_category',
    value: (result) => result.reproducibility.embedding_provider_category,
  },
  {
    header: 'generation_provider_category',
    value: (result) => result.reproducibility.generation_provider_category,
  },
  {
    header: 'embedding_dimensions',
    value: (result) => result.reproducibility.embedding_dimensions,
  },
  {
    header: 'embedding_space_fingerprint',
    value: (result) => result.reproducibility.embedding_space_fingerprint,
  },
  {
    header: 'normalization_mode',
    value: (result) => result.reproducibility.normalization_mode,
  },
  {
    header: 'normalization_fingerprint',
    value: (result) => result.reproducibility.normalization_fingerprint,
  },
  {
    header: 'evaluation_timeout_seconds',
    value: (result) => result.reproducibility.evaluation_timeout_seconds,
  },
  { header: 'sequence', value: (_result, query) => query.sequence },
  { header: 'repetition', value: (_result, query) => query.repetition },
  { header: 'case_id', value: (_result, query) => query.case_id },
  { header: 'category', value: (_result, query) => query.category },
  { header: 'prompt', value: (_result, query) => query.prompt },
  {
    header: 'expected_cache_hit',
    value: (_result, query) => query.expected_cache_hit,
  },
  {
    header: 'expected_match_case_id',
    value: (_result, query) => query.expected_match_case_id,
  },
  { header: 'note', value: (_result, query) => query.note },
  {
    header: 'actual_cache_hit',
    value: (_result, query) => query.actual_cache_hit,
  },
  { header: 'correct', value: (_result, query) => query.correct },
  { header: 'outcome', value: (_result, query) => query.outcome },
  {
    header: 'similarity_score',
    value: (_result, query) => query.similarity_score,
  },
  { header: 'latency_ms', value: (_result, query) => query.latency_ms },
  {
    header: 'provider_called',
    value: (_result, query) => query.provider_called,
  },
  {
    header: 'matched_prompt',
    value: (_result, query) => query.matched_prompt,
  },
  {
    header: 'matched_cache_key',
    value: (_result, query) => query.matched_cache_key,
  },
];

function csvCell(value: CsvValue): string {
  if (value === null) {
    return '';
  }
  const text =
    typeof value === 'string' && /^[=+\-@]/.test(value) ? `'${value}` : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function buildBenchmarkJson(result: BenchmarkRunResponse): string {
  return JSON.stringify(result, null, 2);
}

export function buildBenchmarkCsv(result: BenchmarkRunResponse): string {
  const header = CSV_COLUMNS.map((column) => column.header).join(',');
  const rows = result.query_results.map((query) =>
    CSV_COLUMNS.map((column) => csvCell(column.value(result, query))).join(','),
  );
  return [header, ...rows].join('\r\n');
}

export function downloadBenchmark(
  result: BenchmarkRunResponse,
  format: 'json' | 'csv',
): void {
  const content =
    format === 'json' ? buildBenchmarkJson(result) : buildBenchmarkCsv(result);
  const blob = new Blob([content], {
    type: format === 'json' ? 'application/json' : 'text/csv;charset=utf-8',
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = `semantix-evaluation-${result.run_id}.${format}`;
  anchor.click();
  URL.revokeObjectURL(url);
}

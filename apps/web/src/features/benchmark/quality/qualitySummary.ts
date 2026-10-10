import {
  createEnumGuard,
  isIsoDate,
  isNonEmptyString,
  isNonNegativeInteger,
  isNonNegativeNumber,
  isNumberInRange,
  isRecord,
  isSha256Hex,
} from '@/shared/api/validators';

export interface QualityMetrics {
  cases: number;
  true_positive: number;
  false_positive: number;
  false_negative: number;
  true_negative: number;
  reuse_precision: number | null;
  reuse_recall: number | null;
  false_accept_rate: number | null;
  wrong_among_accepted: number | null;
  false_reject_rate: number | null;
  generation_avoidance: number | null;
}

interface QualityPoint {
  threshold: number;
  calibration: QualityMetrics;
  held_out: QualityMetrics;
}

export interface QualityRun {
  embedding: {
    baseline: string;
    identity: string;
    dimensions: number;
    normalization: string;
    kind: string;
    revision: number | string;
    model_id: string | null;
    model_preprocessing: string;
    runtime_versions: Record<string, string>;
  };
  calibrated_threshold: number;
  sweep: QualityPoint[];
  preprocessing_ns_per_prompt: number;
}

export interface QualitySummary {
  source_sha: string;
  source_dirty: boolean;
  generated_at_utc: string;
  corpus: { version: string; sha256: string; label_review: string };
  calibration_cases: number;
  held_out_cases: number;
  default_threshold: number;
  threshold_grid: number[];
  runs: QualityRun[];
  limitations: string[];
}

const isBaseline = createEnumGuard([
  'token-count',
  'char-trigram',
  'minilm-l6-v2',
] as const);
const isNormalization = createEnumGuard(['raw', 'whitespace', 'NFC'] as const);

const isRate = (value: unknown): value is number => isNumberInRange(value, 0, 1);
const isNullableRate = (value: unknown): value is number | null =>
  value === null || isRate(value);

function isMetrics(value: unknown): value is QualityMetrics {
  if (
    !isRecord(value) ||
    !isNonNegativeInteger(value.cases) ||
    !isNonNegativeInteger(value.true_positive) ||
    !isNonNegativeInteger(value.false_positive) ||
    !isNonNegativeInteger(value.false_negative) ||
    !isNonNegativeInteger(value.true_negative) ||
    !isNullableRate(value.reuse_precision) ||
    !isNullableRate(value.reuse_recall) ||
    !isNullableRate(value.false_accept_rate) ||
    !isNullableRate(value.wrong_among_accepted) ||
    !isNullableRate(value.false_reject_rate) ||
    !isNullableRate(value.generation_avoidance)
  ) {
    return false;
  }
  const tp = value.true_positive;
  const fp = value.false_positive;
  const fn = value.false_negative;
  const tn = value.true_negative;
  const ratio = (a: number, b: number): number | null => (b === 0 ? null : a / b);
  const rates = [
    [value.reuse_precision, ratio(tp, tp + fp)],
    [value.reuse_recall, ratio(tp, tp + fn)],
    [value.false_accept_rate, ratio(fp, fp + tn)],
    [value.wrong_among_accepted, ratio(fp, tp + fp)],
    [value.false_reject_rate, ratio(fn, tp + fn)],
    [value.generation_avoidance, ratio(tp + fp, value.cases)],
  ];
  return (
    tp + fp + fn + tn === value.cases &&
    rates.every(([actual, expected]) =>
      actual === null || expected === null
        ? actual === expected
        : actual !== undefined &&
          expected !== undefined &&
          Math.abs(actual - expected) < 1e-12,
    )
  );
}

function isPoint(value: unknown): value is QualityPoint {
  return (
    isRecord(value) &&
    isRate(value.threshold) &&
    isMetrics(value.calibration) &&
    isMetrics(value.held_out)
  );
}

function isRun(value: unknown): value is QualityRun {
  if (!isRecord(value) || !isRecord(value.embedding)) {
    return false;
  }
  const embedding = value.embedding;
  const versions = embedding.runtime_versions;
  const semantic = embedding.baseline === 'minilm-l6-v2';
  return (
    isBaseline(embedding.baseline) &&
    isNonEmptyString(embedding.identity) &&
    embedding.dimensions === (semantic ? 384 : 2048) &&
    isNormalization(embedding.normalization) &&
    embedding.kind === (semantic ? 'pretrained-semantic' : 'lexical-control') &&
    (semantic
      ? typeof embedding.revision === 'string' &&
        /^[a-f0-9]{40}$/.test(embedding.revision) &&
        embedding.model_id === 'sentence-transformers/all-MiniLM-L6-v2'
      : embedding.revision === 1 && embedding.model_id === null) &&
    isNonEmptyString(embedding.model_preprocessing) &&
    isRecord(versions) &&
    ['python', 'numpy', 'pydantic', 'platform'].every((key) =>
      isNonEmptyString(versions[key]),
    ) &&
    (!semantic ||
      [
        'sentence-transformers',
        'torch',
        'transformers',
        'huggingface-hub',
        'tokenizers',
        'safetensors',
      ].every((key) => isNonEmptyString(versions[key]))) &&
    isRate(value.calibrated_threshold) &&
    isNonNegativeNumber(value.preprocessing_ns_per_prompt) &&
    Array.isArray(value.sweep) &&
    value.sweep.length >= 2 &&
    value.sweep.every(isPoint)
  );
}

function isSummary(value: unknown): value is QualitySummary {
  if (
    !isRecord(value) ||
    value.schema_version !== 1 ||
    value.benchmark !== 'semantix-reuse-quality' ||
    value.evidence_kind !== 'certified-static-benchmark' ||
    value.certification !== 'reviewed' ||
    typeof value.source_sha !== 'string' ||
    !/^[a-f0-9]{40}$/.test(value.source_sha) ||
    value.source_dirty !== false ||
    !isIsoDate(value.generated_at_utc) ||
    !/(Z|\+00:00)$/.test(value.generated_at_utc) ||
    !isRecord(value.corpus) ||
    !isNonEmptyString(value.corpus.version) ||
    !isSha256Hex(value.corpus.sha256) ||
    value.corpus.label_review !== 'maintainer-reviewed' ||
    !isNonNegativeInteger(value.calibration_cases) ||
    value.calibration_cases === 0 ||
    !isNonNegativeInteger(value.held_out_cases) ||
    value.held_out_cases === 0 ||
    !isRate(value.default_threshold) ||
    !Array.isArray(value.threshold_grid) ||
    !value.threshold_grid.every(isRate) ||
    !value.threshold_grid.includes(value.default_threshold) ||
    !Array.isArray(value.runs) ||
    value.runs.length === 0 ||
    !value.runs.every(isRun) ||
    !Array.isArray(value.limitations) ||
    value.limitations.length === 0 ||
    !value.limitations.every(isNonEmptyString)
  ) {
    return false;
  }
  const grid = value.threshold_grid;
  const runs = value.runs;
  return (
    ['raw', 'whitespace', 'NFC'].every((normalization) =>
      runs.some(
        (run) =>
          run.embedding.kind === 'pretrained-semantic' &&
          run.embedding.normalization === normalization,
      ),
    ) &&
    grid.every((threshold, i) => i === 0 || threshold > (grid[i - 1] ?? Infinity)) &&
    new Set(value.runs.map((run) => run.embedding.identity)).size ===
      value.runs.length &&
    value.runs.every(
      (run) =>
        run.sweep.length === grid.length &&
        grid.includes(run.calibrated_threshold) &&
        run.sweep.every(
          (point, i) =>
            point.threshold === grid[i] &&
            point.calibration.cases === value.calibration_cases &&
            point.held_out.cases === value.held_out_cases,
        ),
    )
  );
}

/**
 * Validate static manifest compatibility and confusion-derived rates.
 * Review/source/hash fields are declarations, not independently verified provenance.
 */
export function decodeQualitySummary(value: unknown): QualitySummary {
  if (!isSummary(value)) {
    throw new Error('Static reuse-quality evidence is missing or incompatible.');
  }
  return value;
}

export async function fetchQualitySummary(
  signal: AbortSignal,
): Promise<QualitySummary> {
  const response = await fetch(
    new URL(
      import.meta.env.BASE_URL + 'benchmarks/reuse-quality-summary.json',
      window.location.origin,
    ),
    {
      signal: AbortSignal.any([signal, AbortSignal.timeout(10_000)]),
      cache: 'no-store',
    },
  );
  if (!response.ok) {
    throw new Error('Static reuse-quality evidence is unavailable.');
  }
  const value: unknown = await response.json();
  return decodeQualitySummary(value);
}

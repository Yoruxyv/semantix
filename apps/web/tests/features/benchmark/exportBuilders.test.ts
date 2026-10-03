import { describe, expect, it } from 'vitest';

import {
  buildBenchmarkCsv,
  buildBenchmarkJson,
} from '@/features/benchmark/lib/exportBuilders';
import { benchmarkAnalysisResult } from './support';

describe('benchmark export builders', () => {
  it('keeps the JSON export structurally complete', () => {
    const json = buildBenchmarkJson(benchmarkAnalysisResult);

    expect(JSON.parse(json)).toEqual(benchmarkAnalysisResult);
    expect(JSON.parse(json).reproducibility.measured_threshold).toBe(
      benchmarkAnalysisResult.threshold,
    );
  });

  it('repeats run identity, configuration, and complete case evidence in CSV', () => {
    const csv = buildBenchmarkCsv(benchmarkAnalysisResult);
    const [header, ...rows] = csv.split('\r\n');

    for (const column of [
      'export_schema_version',
      'run_id',
      'dataset_id',
      'dataset_source',
      'dataset_schema_version',
      'dataset_version',
      'dataset_digest',
      'measured_threshold',
      'evaluation_thresholds',
      'configuration_fingerprint',
      'sequence',
      'repetition',
      'case_id',
      'expected_match_case_id',
      'note',
      'outcome',
      'provider_called',
      'matched_prompt',
      'matched_cache_key',
    ]) {
      expect(header).toContain(column);
    }
    expect(rows).toHaveLength(4);
    for (const row of rows) {
      expect(row).toContain(benchmarkAnalysisResult.run_id);
      expect(row).toContain(
        benchmarkAnalysisResult.reproducibility.configuration_fingerprint,
      );
    }
  });

  it('neutralizes every spreadsheet formula prefix without changing JSON', () => {
    const dangerous = structuredClone(benchmarkAnalysisResult);
    dangerous.query_results[0]!.prompt = '-1+2';

    const csv = buildBenchmarkCsv(dangerous);
    const json = buildBenchmarkJson(dangerous);

    for (const neutralized of [
      "'-1+2",
      "'=SUM(A1:A2)",
      "'+cached formula-looking prompt",
      "'@expected-reuse",
    ]) {
      expect(csv).toContain(neutralized);
    }
    expect(JSON.parse(json).query_results[0].prompt).toBe('-1+2');
    expect(JSON.parse(json).query_results[2].prompt).toBe('=SUM(A1:A2)');
  });
});

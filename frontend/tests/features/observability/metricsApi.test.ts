import type { MockedFunction } from 'vitest';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getRuntimeDiagnostics,
  getRuntimeMetrics,
} from '@/features/observability/api/metricsApi';

const metricsPayload = {
  observed_at: '2026-07-19T08:00:00Z',
  uptime_seconds: 120,
  request_count: 10,
  error_count: 1,
  cache_hits: 6,
  cache_misses: 3,
  provider_calls: 3,
  in_flight_coalesced_requests: 0,
  average_latency_ms: 42.5,
  p95_latency_ms: 90,
  latency_sample_size: 10,
  cache_size: 4,
  evictions: 2,
  expirations: 1,
};

const diagnosticsPayload = {
  observed_at: '2026-08-21T08:00:00Z',
  process_scope: 'single_backend_process',
  application_version: '1.0.0',
  embedding_provider_category: 'mock',
  generation_provider_category: 'mock',
  embedding_dimensions: 32,
  embedding_space_fingerprint: 'a'.repeat(64),
  generation_configuration_fingerprint: 'b'.repeat(64),
  cache_backend: 'memory',
  cache_readiness: 'ready',
  normalization_mode: 'identity',
  normalization_algorithm_version: 'identity-v1',
  normalization_fingerprint: 'c'.repeat(64),
  evaluation_timeout_seconds: 300,
  evaluation_max_cases: 50,
  evaluation_max_repetitions: 5,
  evaluation_max_thresholds: 15,
  evaluation_max_request_bytes: 65_536,
  evaluation_dataset_persistence_enabled: false,
  evaluation_history_persistence_enabled: false,
};

describe('runtime metrics API', () => {
  let fetchMock: MockedFunction<typeof fetch>;

  beforeEach(() => {
    fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('requests and decodes runtime metrics', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(metricsPayload), { status: 200 }),
    );

    const result = await getRuntimeMetrics();

    expect(result).toEqual({ ok: true, data: metricsPayload });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/metrics'),
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('rejects negative or malformed counters', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ ...metricsPayload, provider_calls: -1 }), {
        status: 200,
      }),
    );

    const result = await getRuntimeMetrics();

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe('invalid_response');
    }
  });
});

describe('runtime diagnostics API', () => {
  let fetchMock: MockedFunction<typeof fetch>;

  beforeEach(() => {
    fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('requests and strictly decodes runtime diagnostics', async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(diagnosticsPayload), { status: 200 }),
    );

    const result = await getRuntimeDiagnostics();

    expect(result).toEqual({ ok: true, data: diagnosticsPayload });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/api/v1/diagnostics'),
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('accepts bounded custom provider names', async () => {
    const payload = {
      ...diagnosticsPayload,
      embedding_provider_category: 'company.embed-v1',
      generation_provider_category: 'company:generation_v1',
    };
    fetchMock.mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }));

    const result = await getRuntimeDiagnostics();

    expect(result).toEqual({ ok: true, data: payload });
  });

  it.each([
    {
      name: 'malformed fingerprint',
      payload: { ...diagnosticsPayload, embedding_space_fingerprint: 'unsafe' },
    },
    {
      name: 'unsupported readiness state',
      payload: { ...diagnosticsPayload, cache_readiness: 'unknown' },
    },
    {
      name: 'unexpected field',
      payload: { ...diagnosticsPayload, database_url: 'private' },
    },
    {
      name: 'malformed provider name',
      payload: { ...diagnosticsPayload, embedding_provider_category: '../provider' },
    },
  ])('rejects $name', async ({ payload }) => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }));

    const result = await getRuntimeDiagnostics();

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.error.code).toBe('invalid_response');
    }
  });
});

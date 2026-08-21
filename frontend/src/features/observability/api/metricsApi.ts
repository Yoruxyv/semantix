import { request, withSignal } from "@/shared/api/httpClient";
import type { ApiResult } from "@/shared/api/types";
import {
  createEnumGuard,
  isIsoDate,
  isNonEmptyString,
  isNonNegativeNumber,
  isNonNegativeInteger,
  isNullableNonNegativeNumber,
  isRecord,
  isSha256Hex,
} from "@/shared/api/validators";

import type { RuntimeDiagnostics, RuntimeMetrics } from "../types";

const isProviderCategory = createEnumGuard([
  "huggingface",
  "openai",
  "anthropic",
  "gemini",
  "ollama",
  "mock",
] as const);
const isCacheBackend = createEnumGuard(["memory", "pgvector"] as const);
const isCacheReadiness = createEnumGuard(["ready", "unavailable"] as const);
const isNormalizationMode = createEnumGuard([
  "identity",
  "typo_correction",
] as const);
const isNormalizationAlgorithmVersion = createEnumGuard([
  "identity-v1",
  "symspell-compound-v1",
] as const);

function decodeRuntimeMetrics(value: unknown): RuntimeMetrics {
  if (
    !isRecord(value) ||
    !isIsoDate(value.observed_at) ||
    !isNonNegativeNumber(value.uptime_seconds) ||
    !isNonNegativeInteger(value.request_count) ||
    !isNonNegativeInteger(value.error_count) ||
    !isNonNegativeInteger(value.cache_hits) ||
    !isNonNegativeInteger(value.cache_misses) ||
    !isNonNegativeInteger(value.provider_calls) ||
    !isNonNegativeInteger(value.in_flight_coalesced_requests) ||
    !isNullableNonNegativeNumber(value.average_latency_ms) ||
    !isNullableNonNegativeNumber(value.p95_latency_ms) ||
    !isNonNegativeInteger(value.latency_sample_size) ||
    !isNonNegativeInteger(value.cache_size) ||
    !isNonNegativeInteger(value.evictions) ||
    !isNonNegativeInteger(value.expirations)
  ) {
    throw new Error("Invalid runtime metrics response");
  }

  return {
    observed_at: value.observed_at,
    uptime_seconds: value.uptime_seconds,
    request_count: value.request_count,
    error_count: value.error_count,
    cache_hits: value.cache_hits,
    cache_misses: value.cache_misses,
    provider_calls: value.provider_calls,
    in_flight_coalesced_requests:
      value.in_flight_coalesced_requests,
    average_latency_ms: value.average_latency_ms,
    p95_latency_ms: value.p95_latency_ms,
    latency_sample_size: value.latency_sample_size,
    cache_size: value.cache_size,
    evictions: value.evictions,
    expirations: value.expirations,
  };
}

export function getRuntimeMetrics(
  signal?: AbortSignal,
): Promise<ApiResult<RuntimeMetrics>> {
  return request(
    "/api/v1/metrics",
    decodeRuntimeMetrics,
    withSignal({ method: "GET" }, signal),
  );
}

function decodeRuntimeDiagnostics(value: unknown): RuntimeDiagnostics {
  if (
    !isRecord(value) ||
    Object.keys(value).length !== 20 ||
    !isIsoDate(value.observed_at) ||
    value.process_scope !== "single_backend_process" ||
    !isNonEmptyString(value.application_version) ||
    !isProviderCategory(value.embedding_provider_category) ||
    !isProviderCategory(value.generation_provider_category) ||
    !isNonNegativeInteger(value.embedding_dimensions) ||
    value.embedding_dimensions === 0 ||
    !isSha256Hex(value.embedding_space_fingerprint) ||
    !isSha256Hex(value.generation_configuration_fingerprint) ||
    !isCacheBackend(value.cache_backend) ||
    !isCacheReadiness(value.cache_readiness) ||
    !isNormalizationMode(value.normalization_mode) ||
    !isNormalizationAlgorithmVersion(
      value.normalization_algorithm_version,
    ) ||
    !isSha256Hex(value.normalization_fingerprint) ||
    !isNonNegativeNumber(value.evaluation_timeout_seconds) ||
    value.evaluation_timeout_seconds === 0 ||
    !isNonNegativeInteger(value.evaluation_max_cases) ||
    value.evaluation_max_cases === 0 ||
    !isNonNegativeInteger(value.evaluation_max_repetitions) ||
    value.evaluation_max_repetitions === 0 ||
    !isNonNegativeInteger(value.evaluation_max_thresholds) ||
    value.evaluation_max_thresholds < 2 ||
    !isNonNegativeInteger(value.evaluation_max_request_bytes) ||
    value.evaluation_max_request_bytes < 1_024 ||
    typeof value.evaluation_dataset_persistence_enabled !== "boolean" ||
    typeof value.evaluation_history_persistence_enabled !== "boolean"
  ) {
    throw new Error("Invalid runtime diagnostics response");
  }

  return {
    observed_at: value.observed_at,
    process_scope: value.process_scope,
    application_version: value.application_version,
    embedding_provider_category: value.embedding_provider_category,
    generation_provider_category: value.generation_provider_category,
    embedding_dimensions: value.embedding_dimensions,
    embedding_space_fingerprint: value.embedding_space_fingerprint,
    generation_configuration_fingerprint:
      value.generation_configuration_fingerprint,
    cache_backend: value.cache_backend,
    cache_readiness: value.cache_readiness,
    normalization_mode: value.normalization_mode,
    normalization_algorithm_version:
      value.normalization_algorithm_version,
    normalization_fingerprint: value.normalization_fingerprint,
    evaluation_timeout_seconds: value.evaluation_timeout_seconds,
    evaluation_max_cases: value.evaluation_max_cases,
    evaluation_max_repetitions: value.evaluation_max_repetitions,
    evaluation_max_thresholds: value.evaluation_max_thresholds,
    evaluation_max_request_bytes: value.evaluation_max_request_bytes,
    evaluation_dataset_persistence_enabled:
      value.evaluation_dataset_persistence_enabled,
    evaluation_history_persistence_enabled:
      value.evaluation_history_persistence_enabled,
  };
}

export function getRuntimeDiagnostics(
  signal?: AbortSignal,
): Promise<ApiResult<RuntimeDiagnostics>> {
  return request(
    "/api/v1/diagnostics",
    decodeRuntimeDiagnostics,
    withSignal({ method: "GET" }, signal),
  );
}

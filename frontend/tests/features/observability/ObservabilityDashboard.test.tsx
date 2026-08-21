import type { QueryClient } from "@tanstack/react-query";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QueryTestProvider } from "../QueryTestProvider";
import { createTestQueryClient } from "../queryClient";
import {
  getRuntimeDiagnostics,
  getRuntimeMetrics,
} from "@/features/observability/api/metricsApi";
import { ObservabilityDashboard } from "@/features/observability/components/ObservabilityDashboard";
import { deferred } from "../support";

vi.mock("@/features/observability/api/metricsApi");

const metrics = {
  observed_at: "2026-07-19T08:00:00Z",
  uptime_seconds: 3_900,
  request_count: 12,
  error_count: 1,
  cache_hits: 7,
  cache_misses: 4,
  provider_calls: 4,
  in_flight_coalesced_requests: 2,
  average_latency_ms: 25.5,
  p95_latency_ms: 80.25,
  latency_sample_size: 12,
  cache_size: 5,
  evictions: 3,
  expirations: 2,
};

const diagnostics = {
  observed_at: "2026-08-21T08:00:00Z",
  process_scope: "single_backend_process" as const,
  application_version: "1.0.0",
  embedding_provider_category: "mock" as const,
  generation_provider_category: "mock" as const,
  embedding_dimensions: 32,
  embedding_space_fingerprint: "a".repeat(64),
  generation_configuration_fingerprint: "b".repeat(64),
  cache_backend: "memory" as const,
  cache_readiness: "ready" as const,
  normalization_mode: "identity" as const,
  normalization_algorithm_version: "identity-v1" as const,
  normalization_fingerprint: "c".repeat(64),
  evaluation_timeout_seconds: 300,
  evaluation_max_cases: 50,
  evaluation_max_repetitions: 5,
  evaluation_max_thresholds: 15,
  evaluation_max_request_bytes: 65_536,
  evaluation_dataset_persistence_enabled: false,
  evaluation_history_persistence_enabled: false,
};

let queryClient: QueryClient;

function renderDashboard(ui = <ObservabilityDashboard />) {
  return render(ui, {
    wrapper: ({ children }: Readonly<{ children: ReactNode }>) => (
      <QueryTestProvider client={queryClient}>
        {children}
      </QueryTestProvider>
    ),
  });
}

beforeEach(() => {
  queryClient = createTestQueryClient();
  vi.mocked(getRuntimeMetrics).mockReset();
  vi.mocked(getRuntimeDiagnostics).mockReset();
  vi.mocked(getRuntimeDiagnostics).mockResolvedValue({
    ok: true,
    data: diagnostics,
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ObservabilityDashboard", () => {
  it("uses a skeleton before rendering live metrics", async () => {
    let resolveMetrics:
      | ((value: Awaited<ReturnType<typeof getRuntimeMetrics>>) => void)
      | undefined;
    vi.mocked(getRuntimeMetrics).mockReturnValue(
      new Promise((resolve) => {
        resolveMetrics = resolve;
      }),
    );

    renderDashboard();

    expect(
      screen.getByLabelText("Loading runtime metrics"),
    ).toBeTruthy();
    expect(
      document.querySelectorAll("[data-skeleton-runtime-metric]"),
    ).toHaveLength(12);

    await act(async () => {
      resolveMetrics?.({ ok: true, data: metrics });
    });

    expect(await screen.findAllByText("12")).toHaveLength(2);
    expect(screen.getByText("25.5 ms")).toBeTruthy();
    expect(screen.getByText("80.3 ms")).toBeTruthy();
    expect(
      screen.queryByLabelText("Loading runtime metrics"),
    ).toBeNull();

    const cacheGrid = screen.getByText("Cache").closest("section")
      ?.querySelector("dl");
    expect(cacheGrid?.children).toHaveLength(5);
    expect(cacheGrid?.className).toContain("flex-wrap");
    expect(cacheGrid?.firstElementChild?.className).toContain("grow");
    expect(cacheGrid?.firstElementChild?.className).toContain(
      "basis-56",
    );
  });

  it("renders an endpoint error without simulated fallback data", async () => {
    vi.mocked(getRuntimeMetrics).mockResolvedValue({
      ok: false,
      error: {
        code: "network_error",
        detail: "Backend unavailable",
        status: null,
      },
    });

    renderDashboard();

    expect(await screen.findByText("Backend unavailable")).toBeTruthy();
    expect(screen.queryByText("25.5 ms")).toBeNull();
  });

  it("renders safe read-only diagnostics with full wrapping fingerprints", async () => {
    vi.mocked(getRuntimeMetrics).mockResolvedValue({ ok: true, data: metrics });

    renderDashboard();

    const heading = await screen.findByRole("heading", {
      name: "Runtime diagnostics",
    });
    const panel = heading.closest("section");
    expect(panel).not.toBeNull();
    expect(await screen.findByText("One backend process")).toBeTruthy();
    expect(screen.getByText("Ready")).toBeTruthy();
    expect(screen.getByText(/Runtime diagnostics observed/)).toBeTruthy();
    expect(screen.getByText(diagnostics.embedding_space_fingerprint)).toBeTruthy();
    expect(
      screen.getByText(diagnostics.embedding_space_fingerprint).className,
    ).toContain("break-all");
    expect(panel?.querySelectorAll("input, select, textarea")).toHaveLength(0);
    expect(
      panel?.querySelector("[data-runtime-diagnostics-grid]")?.className,
    ).toContain("lg:grid-cols-2");
  });

  it("distinguishes diagnostics loading and initial failure", async () => {
    vi.mocked(getRuntimeMetrics).mockResolvedValue({ ok: true, data: metrics });
    const request = deferred<Awaited<ReturnType<typeof getRuntimeDiagnostics>>>();
    vi.mocked(getRuntimeDiagnostics).mockReturnValue(request.promise);

    renderDashboard();

    expect(
      screen.getByLabelText("Loading runtime diagnostics"),
    ).toBeTruthy();

    await act(async () => {
      request.resolve({
        ok: false,
        error: {
          code: "network_error",
          detail: "Diagnostics backend unavailable",
          status: null,
        },
      });
    });

    expect(
      await screen.findByText("Diagnostics backend unavailable"),
    ).toBeTruthy();
    expect(screen.queryByText("One backend process")).toBeNull();
  });

  it("keeps stale diagnostics visible after a refresh failure", async () => {
    vi.mocked(getRuntimeMetrics).mockResolvedValue({ ok: true, data: metrics });
    vi.mocked(getRuntimeDiagnostics)
      .mockResolvedValueOnce({ ok: true, data: diagnostics })
      .mockResolvedValueOnce({
        ok: false,
        error: {
          code: "network_error",
          detail: "Refresh failed safely",
          status: null,
        },
      });

    renderDashboard();
    await screen.findByText("One backend process");

    fireEvent.click(
      screen.getByRole("button", { name: "Refresh diagnostics" }),
    );

    expect(await screen.findByText("Refresh failed safely")).toBeTruthy();
    expect(screen.getByText("Diagnostics may be stale")).toBeTruthy();
    expect(screen.getByText("One backend process")).toBeTruthy();
  });

  it("reports cache readiness without relying on color", async () => {
    vi.mocked(getRuntimeMetrics).mockResolvedValue({ ok: true, data: metrics });
    vi.mocked(getRuntimeDiagnostics).mockResolvedValue({
      ok: true,
      data: { ...diagnostics, cache_readiness: "unavailable" },
    });

    renderDashboard();

    expect(await screen.findByText("Unavailable")).toBeTruthy();
  });

  it("deduplicates simultaneous consumers of runtime metrics", async () => {
    const request =
      deferred<Awaited<ReturnType<typeof getRuntimeMetrics>>>();
    vi.mocked(getRuntimeMetrics).mockReturnValue(request.promise);

    renderDashboard(
      <>
        <ObservabilityDashboard />
        <ObservabilityDashboard />
      </>,
    );

    expect(getRuntimeMetrics).toHaveBeenCalledOnce();
    expect(
      screen.getAllByLabelText("Loading runtime metrics"),
    ).toHaveLength(2);

    await act(async () => {
      request.resolve({ ok: true, data: metrics });
    });

    expect(await screen.findAllByText("25.5 ms")).toHaveLength(2);
  });

  it("disables and coalesces manual refresh while a request is active", async () => {
    vi.mocked(getRuntimeMetrics).mockResolvedValueOnce({
      ok: true,
      data: metrics,
    });
    const refresh =
      deferred<Awaited<ReturnType<typeof getRuntimeMetrics>>>();
    vi.mocked(getRuntimeMetrics).mockReturnValueOnce(refresh.promise);

    renderDashboard();
    await screen.findByText("25.5 ms");

    const button = screen.getByRole<HTMLButtonElement>("button", {
      name: "Refresh metrics",
    });
    fireEvent.click(button);

    await waitFor(() => expect(button.disabled).toBe(true));
    fireEvent.click(button);
    expect(screen.getByText("25.5 ms")).toBeTruthy();
    expect(screen.getByText("Refreshing runtime metrics")).toBeTruthy();
    expect(getRuntimeMetrics).toHaveBeenCalledTimes(2);

    await act(async () => {
      refresh.resolve({
        ok: true,
        data: { ...metrics, request_count: 13 },
      });
    });
    await waitFor(() => {
      expect(screen.queryByText("Refreshing runtime metrics")).toBeNull();
    });
  });

  it("stops metrics polling after the last consumer unmounts", async () => {
    vi.useFakeTimers();
    vi.mocked(getRuntimeMetrics).mockResolvedValue({
      ok: true,
      data: metrics,
    });

    try {
      const { unmount } = renderDashboard();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(getRuntimeMetrics).toHaveBeenCalledOnce();

      await act(async () => {
        await vi.advanceTimersByTimeAsync(5_000);
      });
      expect(getRuntimeMetrics).toHaveBeenCalledTimes(2);

      unmount();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(15_000);
      });
      expect(getRuntimeMetrics).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
});
});

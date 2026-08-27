import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "@/App";
import { FieldMetrics } from "@/features/monitor/components/FieldMetrics";
import { QueryLog } from "@/features/monitor/components/QueryLog";
import { ResponseCard } from "@/features/monitor/components/ResponseCard";
import { SimilarityRadar } from "@/features/monitor/components/similarity-radar/SimilarityRadar";
import { useQuery } from "@/features/monitor/hooks/useQuery";
import {
  getCacheStats,
  getCacheThreshold,
  listCacheEntries,
} from "@/features/cache/api/cacheApi";
import { getBenchmarkDatasets } from "@/features/benchmark/api/benchmarkApi";
import type { QueryTrace } from "@/features/monitor/types";

vi.mock("../../../src/features/monitor/hooks/useQuery");
vi.mock("../../../src/features/cache/api/cacheApi");
vi.mock("../../../src/features/benchmark/api/benchmarkApi");

const traces: QueryTrace[] = [
  {
    id: "scored-hit",
    prompt: "Close match",
    similarity: 0.95,
    latencyMs: 10,
    recordedAt: new Date("2026-07-17T10:00:00Z"),
    actualCacheHit: true,
    namespace: "tenant-a",
    policyMode: "normal",
    providerCalled: false,
  },
  {
    id: "scored-miss",
    prompt: "Distant match",
    similarity: 0.4,
    latencyMs: 20,
    recordedAt: new Date("2026-07-17T10:01:00Z"),
    actualCacheHit: false,
    namespace: "tenant-a",
    policyMode: "read-only",
    providerCalled: true,
  },
  {
    id: "unscored-miss",
    prompt: "First cache query",
    similarity: null,
    latencyMs: 30,
    recordedAt: new Date("2026-07-17T10:02:00Z"),
    actualCacheHit: false,
    namespace: "tenant-b",
    policyMode: "bypass",
    providerCalled: false,
  },
];

function metricValue(label: string): string | null | undefined {
  const labelElement = screen.getByText(label);
  const row = labelElement.closest("div");
  return row?.querySelector("dd")?.textContent;
}

describe("dashboard correctness", () => {
  beforeEach(() => {
    vi.stubGlobal("crypto", {
      randomUUID: vi.fn(() => "trace-id"),
    });
    vi.mocked(useQuery).mockReturnValue({
      state: { status: "idle" },
      submit: vi.fn().mockResolvedValue(null),
    });
    vi.mocked(getCacheStats).mockResolvedValue({
      ok: true,
      data: { size: 7, hits: 1, misses: 3, hit_rate: 0.25 },
    });
    vi.mocked(getCacheThreshold).mockResolvedValue({
      ok: true,
      data: { threshold: 0.9 },
    });
    vi.mocked(getBenchmarkDatasets).mockResolvedValue({
      ok: true,
      data: {
        datasets: [
          {
            dataset_id: "quick",
            dataset_source: "builtin",
            schema_version: null,
            version: "1.0.0",
            digest: "d".repeat(64),
            name: "Quick semantic safety set",
            description: "Controlled prompts.",
            query_count: 8,
            expected_hits: 4,
            expected_misses: 4,
            categories: [
              "seed",
              "exact_duplicate",
              "paraphrase",
              "unrelated",
              "typo",
              "negation",
              "different_intent",
            ],
          },
        ],
        default_dataset_id: "quick",
      },
    });
    vi.mocked(listCacheEntries).mockResolvedValue({
      ok: true,
      data: {
        items: [],
        total: 0,
        offset: 0,
        limit: 10,
        has_more: false,
      },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("starts without simulated radar traces", async () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByText("0 of 0 traces plotted")).toBeTruthy();
    expect(container.querySelectorAll('[data-testid="similarity-point"]')).toHaveLength(0);
  });

  it("shows a cache-readings skeleton while initial workspace data loads", async () => {
    vi.mocked(getCacheStats).mockReturnValue(
      new Promise(() => undefined),
    );
    vi.mocked(getCacheThreshold).mockReturnValue(
      new Promise(() => undefined),
    );

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    expect(
      await screen.findByLabelText("Loading cache readings"),
    ).toBeTruthy();
    expect(
      document.querySelectorAll("[data-skeleton-reading]"),
    ).toHaveLength(6);
    expect(
      document.querySelector("[data-skeleton-similarity-plot]"),
    ).toBeTruthy();
  });

  it("reserves response space while a query is running", async () => {
    vi.mocked(useQuery).mockReturnValue({
      state: { status: "loading" },
      submit: vi.fn().mockResolvedValue(null),
    });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    expect(
      await screen.findByLabelText("Loading query response"),
    ).toBeTruthy();
    expect(
      document.querySelectorAll("[data-skeleton-evidence-metric]"),
    ).toHaveLength(7);
  });

  it("preserves an API null similarity when adding an application trace", async () => {
    vi.mocked(useQuery).mockReturnValue({
      state: { status: "idle" },
      submit: vi.fn().mockResolvedValue({
        response: "Generated response",
        cache_hit: false,
        similarity_score: null,
        similarity_threshold: 0.9,
        matched_prompt: null,
        matched_cache_key: null,
        cache_entry_created_at: null,
        cache_entry_age_seconds: null,
        generation_skipped: false,
        provider_called: true,
        latency_ms: 12,
      }),
    });
    const { container } = render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByLabelText("Query text"), {
      target: { value: "First cache query" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));

    expect(await screen.findByText("First cache query")).toBeTruthy();
    expect(screen.getByText("0 of 1 traces plotted")).toBeTruthy();
    expect(screen.getByText("MISS")).toBeTruthy();
    expect(screen.getByText("default · Normal read and write")).toBeTruthy();
    expect(container.querySelectorAll('[data-testid="similarity-point"]')).toHaveLength(0);
  });

  it("renders the deferred response card after a successful query", async () => {
    vi.mocked(useQuery).mockReturnValue({
      state: {
        status: "success",
        data: {
          response: "Generated response",
          cache_hit: false,
          similarity_score: null,
          similarity_threshold: 0.9,
          matched_prompt: null,
          matched_cache_key: null,
          cache_entry_created_at: null,
          cache_entry_age_seconds: null,
          generation_skipped: false,
          provider_called: true,
          latency_ms: 12,
        },
      },
      submit: vi.fn().mockResolvedValue(null),
    });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole("heading", { name: "Latest response" }),
    ).toBeTruthy();
  });

  it("omits private prompt and response content from recent query traces", async () => {
    const privatePrompt = "Private customer incident";
    const privateResponse = "Private provider response";
    const submit = vi.fn().mockResolvedValue({
      response: privateResponse,
      cache_hit: false,
      similarity_score: null,
      similarity_threshold: 0.9,
      matched_prompt: null,
      matched_cache_key: null,
      cache_entry_created_at: null,
      cache_entry_age_seconds: null,
      generation_skipped: false,
      provider_called: true,
      latency_ms: 12,
    });
    vi.mocked(useQuery).mockReturnValue({
      state: { status: "idle" },
      submit,
    });
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByText("Advanced cache policy"));
    fireEvent.click(
      screen.getByRole("radio", { name: /^Private request/ }),
    );
    fireEvent.change(screen.getByLabelText("Query text"), {
      target: { value: privatePrompt },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run query" }));

    await waitFor(() => expect(submit).toHaveBeenCalledOnce());
    const trace = screen
      .getByRole("heading", { name: "Recent query trace" })
      .closest("section");
    expect(trace).not.toBeNull();
    expect(within(trace!).getByText("00 records")).toBeTruthy();
    expect(within(trace!).queryByText(privatePrompt)).toBeNull();
    expect(within(trace!).queryByText(privateResponse)).toBeNull();
  });

  it("plots only scored traces and keeps their positions stable across thresholds", () => {
    const onThresholdChange = vi.fn();
    const onThresholdCommit = vi.fn();
    const { container, rerender } = render(
      <SimilarityRadar
        appliedThreshold={0.9}
        canApplyThreshold
        isApplyingThreshold={false}
        traces={traces}
        threshold={0.9}
        onThresholdApply={onThresholdCommit}
        onThresholdChange={onThresholdChange}
      />,
    );

    expect(screen.getByText("2 of 3 traces plotted")).toBeTruthy();
    expect(container.querySelectorAll('[data-testid="similarity-point"]')).toHaveLength(2);
    expect(container.querySelector('[data-trace-id="unscored-miss"]')).toBeNull();

    const point = container.querySelector('[data-trace-id="scored-hit"]');
    const initialPosition = [point?.getAttribute("cx"), point?.getAttribute("cy")];

    rerender(
      <SimilarityRadar
        appliedThreshold={0.9}
        canApplyThreshold
        isApplyingThreshold={false}
        traces={traces}
        threshold={0.99}
        onThresholdApply={onThresholdCommit}
        onThresholdChange={onThresholdChange}
      />,
    );

    const rerenderedPoint = container.querySelector('[data-trace-id="scored-hit"]');
    expect([
      rerenderedPoint?.getAttribute("cx"),
      rerenderedPoint?.getAttribute("cy"),
    ]).toEqual(initialPosition);
  });

  it("shows and highlights trace evidence on hover and keyboard focus", () => {
    render(
      <SimilarityRadar
        appliedThreshold={0.9}
        canApplyThreshold
        isApplyingThreshold={false}
        traces={traces}
        threshold={0.9}
        onThresholdApply={vi.fn()}
        onThresholdChange={vi.fn()}
      />,
    );

    const point = screen.getByRole("button", {
      name: /Prompt: Close match\./,
    });
    expect(
      screen.getByRole("button", {
        name: /Inspect Close match\. Similarity 0\.950\. Projected HIT\./,
      }),
    ).toBeTruthy();
    const pointGroup = point.closest("g");

    fireEvent.mouseEnter(point);

    const hoverTooltip = screen.getByRole("tooltip");
    expect(hoverTooltip.textContent).toContain("Close match");
    expect(hoverTooltip.textContent).toContain("Score 0.950");
    expect(hoverTooltip.textContent).toContain("Preview HIT");
    expect(hoverTooltip.textContent).toContain("Actual HIT");
    expect(pointGroup?.getAttribute("data-active")).toBe("true");
    expect(
      pointGroup
        ?.querySelector('[data-testid="similarity-point"]')
        ?.getAttribute("r"),
    ).toBe("8");

    fireEvent.mouseLeave(point);
    expect(screen.queryByRole("tooltip")).toBeNull();

    fireEvent.focus(point);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    expect(pointGroup?.getAttribute("data-active")).toBe("true");

    fireEvent.blur(point);
    expect(screen.queryByRole("tooltip")).toBeNull();

    fireEvent.click(point);
    expect(screen.getByRole("tooltip")).toBeTruthy();
    expect(pointGroup?.getAttribute("data-active")).toBe("true");
  });

  it("renders missing similarity as n/a and classifies it as a miss", () => {
    const unscoredTrace = traces[2];
    expect(unscoredTrace).toBeDefined();
    render(
      <QueryLog
        traces={unscoredTrace === undefined ? [] : [unscoredTrace]}
        threshold={0.9}
      />,
    );

    expect(screen.getByText("n/a")).toBeTruthy();
    expect(screen.getByText("MISS")).toBeTruthy();
  });

  it("renders a nullable response similarity as n/a", () => {
    render(
      <ResponseCard
        result={{
          response: "Generated response",
          cache_hit: false,
          similarity_score: null,
          similarity_threshold: 0.9,
          matched_prompt: null,
          matched_cache_key: null,
          cache_entry_created_at: null,
          cache_entry_age_seconds: null,
          generation_skipped: false,
          provider_called: true,
          latency_ms: 12,
        }}
      />,
    );

    const similarityLabel = screen.getByText("Similarity");
    expect(
      similarityLabel.parentElement?.querySelector("dd")?.textContent,
    ).toBe("n/a");
  });

  it("uses scored-only projection and explicit metric formulas", () => {
    render(
      <FieldMetrics
        cacheStats={{ size: 7, hits: 1, misses: 3, hit_rate: 0.25 }}
        threshold={0.9}
        traces={traces}
      />,
    );

    expect(metricValue("Frontend projected hit rate")).toBe("50.0%");
    expect(metricValue("Actual backend hit rate")).toBe("25.0%");
    expect(metricValue("Scored / unscored queries")).toBe("2 / 1");
    expect(metricValue("Mean latency")).toBe("20.0 ms");
    expect(metricValue("Provider calls (visible)")).toBe("1");
    expect(metricValue("Cache entries")).toBe("7");
    expect(
      screen.getByText(
        "scored visible traces at or above threshold ÷ scored visible traces",
      ),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "backend hits ÷ (backend hits + backend misses), since the last reset",
      ),
    ).toBeTruthy();
  });
});

import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { ResponseCard } from "@/features/monitor/components/ResponseCard";
import type { QueryResponse } from "@/features/monitor/types";

const missResult: QueryResponse = {
  response: "Generated response",
  cache_hit: false,
  similarity_score: null,
  similarity_threshold: 0.92,
  matched_prompt: null,
  matched_cache_key: null,
  cache_entry_created_at: null,
  cache_entry_age_seconds: null,
  generation_skipped: false,
  provider_called: true,
  latency_ms: 12,
};

function detailValue(label: string): string | null | undefined {
  const labelElement = screen.getByText(label);
  return labelElement.parentElement?.querySelector("dd")?.textContent;
}

describe("ResponseCard math rendering", () => {
  afterEach(cleanup);

  it("renders dollar and LaTeX math delimiters with KaTeX", () => {
    const { container } = render(
      <ResponseCard
        result={{
          ...missResult,
          response: [
            "Inline dollar math: $x^2 + y^2 = z^2$.",
            "Inline LaTeX math: \\(E = mc^2\\).",
            "",
            "\\[",
            "\\int_0^1 x^2\\,dx = \\frac{1}{3}",
            "\\]",
          ].join("\n"),
        }}
      />,
    );

    expect(container.querySelectorAll(".katex")).toHaveLength(3);
    expect(
      container.querySelectorAll(".katex-display"),
    ).toHaveLength(1);
  });

  it("does not transform math delimiters inside code", () => {
    const { container } = render(
      <ResponseCard
        result={{
          ...missResult,
          response:
            "Use `\\(not rendered as math\\)` in this example.",
        }}
      />,
    );

    expect(container.querySelector(".katex")).toBeNull();
    expect(container.querySelector("code")?.textContent).toBe(
      "\\(not rendered as math\\)",
    );
  });

  it("renders markdown tables with scoped column headers", () => {
    const { container } = render(
      <ResponseCard
        result={{
          ...missResult,
          response: [
            "| Provider | Capability |",
            "| --- | --- |",
            "| Anthropic | Generation |",
          ].join("\n"),
        }}
      />,
    );

    const headers = container.querySelectorAll(
      "table thead th[scope='col']",
    );
    expect(headers).toHaveLength(2);
    expect(headers[0]?.textContent).toBe("Provider");
    expect(headers[1]?.textContent).toBe("Capability");
  });

  it("renders every explainability field for a cache hit", () => {
    render(
      <MemoryRouter>
        <ResponseCard
          evidence={{ namespace: "tenant-a", policyMode: "normal" }}
          result={{
            response: "Cached response",
            cache_hit: true,
            similarity_score: 0.97,
            similarity_threshold: 0.92,
            matched_prompt: "Explain semantic caching",
            matched_cache_key: "a".repeat(64),
            cache_entry_created_at: "2026-07-17T10:00:00Z",
            cache_entry_age_seconds: 125,
            generation_skipped: true,
            provider_called: false,
            latency_ms: 8.25,
          }}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("CACHE HIT")).toBeTruthy();
    expect(detailValue("Similarity")).toBe("0.970");
    expect(detailValue("Threshold used")).toBe("0.920");
    expect(detailValue("Matched cached prompt")).toBe(
      "Explain semantic caching",
    );
    expect(detailValue("Cache entry age")).toBe("2m 5s");
    expect(detailValue("Generation")).toBe("Skipped");
    expect(detailValue("Provider")).toBe("Not called");
    expect(detailValue("Request latency")).toBe("8.3 ms");
    expect(
      screen.getByText(
        "Effective namespace: tenant-a · Policy: Normal read and write.",
      ),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Open matched live cache entry" })
        .getAttribute("href"),
    ).toBe(`/cache/entries/${"a".repeat(64)}`);
  });

  it("renders explicit miss explainability without matched-entry values", () => {
    render(
      <ResponseCard
        result={{
          ...missResult,
          similarity_score: 0.41,
        }}
      />,
    );

    expect(screen.getByText("FRESH RESPONSE")).toBeTruthy();
    expect(detailValue("Similarity")).toBe("0.410");
    expect(detailValue("Threshold used")).toBe("0.920");
    expect(detailValue("Matched cached prompt")).toBe(
      "No cached entry reused",
    );
    expect(detailValue("Cache entry age")).toBe("n/a");
    expect(detailValue("Generation")).toBe("Ran");
    expect(detailValue("Provider")).toBe("Called");
    expect(detailValue("Request latency")).toBe("12.0 ms");
    expect(
      screen.queryByRole("link", { name: "Open matched live cache entry" }),
    ).toBeNull();
  });

  it("explains a coalesced miss without claiming a provider call", () => {
    render(
      <ResponseCard
        result={{
          ...missResult,
          response: "Shared in-flight response",
          generation_skipped: true,
          provider_called: false,
        }}
      />,
    );

    expect(screen.getByText("COALESCED RESPONSE")).toBeTruthy();
    expect(
      screen.getByText(
        "Awaited an identical in-flight request instead of making a duplicate provider call.",
      ),
    ).toBeTruthy();
    expect(detailValue("Generation")).toBe("Skipped");
    expect(detailValue("Provider")).toBe("Not called");
  });
});

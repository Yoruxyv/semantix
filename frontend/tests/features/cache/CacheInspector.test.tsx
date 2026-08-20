import type { QueryClient } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { QueryTestProvider } from "../QueryTestProvider";
import { createTestQueryClient } from "../queryClient";
import { CacheInspector } from "@/features/cache/components/CacheInspector";
import {
  clearCache,
  deleteCacheEntry,
  getCacheEntry,
  listCacheEntries,
} from "@/features/cache/api/cacheApi";
import type {
  CacheEntryListParams,
  CacheEntryMetadata,
} from "@/features/cache/types";
import { benchmarkDatasetKeys, cacheEntryKeys } from "@/shared/query/queryKeys";
import { deferred } from "../support";


vi.mock("../../../src/features/cache/api/cacheApi");

const alphaEntry: CacheEntryMetadata = {
  cache_key: "a".repeat(64),
  namespace: "tenant-alpha",
  prompt: "Explain semantic caching",
  response_preview: "Semantic caching reuses related responses.",
  response_preview_truncated: false,
  response: null,
  created_at: "2026-07-17T10:00:00Z",
  expires_at: "2026-07-17T11:00:00Z",
  remaining_ttl_seconds: 125,
  hit_count: 4,
  last_accessed_at: "2026-07-17T10:30:00Z",
  recency_rank: 1,
  is_expired: false,
};

const betaEntry: CacheEntryMetadata = {
  cache_key: "b".repeat(64),
  namespace: "tenant-beta",
  prompt: "How does cosine similarity work?",
  response_preview: "Cosine similarity compares vector direction.",
  response_preview_truncated: false,
  response: null,
  created_at: "2026-07-17T09:00:00Z",
  expires_at: "2026-07-17T10:30:00Z",
  remaining_ttl_seconds: 60,
  hit_count: 1,
  last_accessed_at: null,
  recency_rank: 2,
  is_expired: false,
};

function successfulPage(
  items: CacheEntryMetadata[],
  params: CacheEntryListParams,
) {
  return {
    ok: true as const,
    data: {
      items,
      total: items.length,
      offset: params.offset,
      limit: params.limit,
      has_more: false,
    },
  };
}

let queryClient: QueryClient;

function renderInspector(
  onMutation = vi.fn(),
  initialEntry = "/cache",
) {
  return render(<CacheInspector onMutation={onMutation} />, {
    wrapper: ({ children }: Readonly<{ children: ReactNode }>) => (
      <QueryTestProvider client={queryClient}>
        <MemoryRouter initialEntries={[initialEntry]}>
          {children}
        </MemoryRouter>
      </QueryTestProvider>
    ),
  });
}

describe("CacheInspector", () => {
  beforeEach(() => {
    queryClient = createTestQueryClient();
    vi.mocked(listCacheEntries).mockImplementation(async (params) =>
      successfulPage([], params),
    );
    vi.mocked(deleteCacheEntry).mockResolvedValue({
      ok: true,
      data: { deleted: true, cache_key: alphaEntry.cache_key },
    });
    vi.mocked(getCacheEntry).mockResolvedValue({
      ok: true,
      data: {
        ...alphaEntry,
        response: alphaEntry.response_preview,
      },
    });
    vi.mocked(clearCache).mockResolvedValue({
      ok: true,
      data: { cleared: true },
    });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("renders the empty state", async () => {
    renderInspector();

    expect(await screen.findByText("The cache is empty.")).toBeTruthy();
    expect(
      screen.getByText("Run a query to create the first inspectable entry."),
    ).toBeTruthy();
  });

  it("renders a contextual loading skeleton before entries resolve", () => {
    vi.mocked(listCacheEntries).mockReturnValue(
      new Promise(() => undefined),
    );

    renderInspector();

    expect(screen.getByLabelText("Loading cache entries")).toBeTruthy();
    expect(
      document.querySelectorAll("[data-skeleton-entry-metric]"),
    ).toHaveLength(12);
  });

  it("renders markdown and math in response previews", async () => {
    const formattedEntry = {
      ...alphaEntry,
      response_preview: [
        "**Formatted preview**",
        "",
        "- First item",
        "- Second item",
        "",
        "Inline math: \\(x^2 + y^2\\)",
      ].join("\n"),
    };
    vi.mocked(listCacheEntries).mockImplementation(async (params) =>
      successfulPage([formattedEntry], params),
    );

    const { container } = renderInspector();

    const strongText = await screen.findByText("Formatted preview");
    expect(strongText.tagName).toBe("STRONG");
    expect(screen.getByText("First item").closest("ul")).not.toBeNull();
    expect(container.querySelector(".katex")).not.toBeNull();
  });

  it("loads complete Markdown instead of rendering a sliced raw preview", async () => {
    const completeMarkdown = [
      `${"a".repeat(232)} **Bold crossing the old boundary**`,
      "",
      "*Italic evidence*",
      "",
      "- First complete item",
      "- Second complete item",
      "",
      "Use `inlineValue` and read the [safe link](https://example.com/cache).",
      "",
      "```ts",
      "const complete = true;",
      "```",
      "",
      "Plain text remains readable.",
      "",
      '<script>alert("unsafe")</script>',
    ].join("\n");
    const truncatedEntry: CacheEntryMetadata = {
      ...alphaEntry,
      response_preview:
        "Response exceeds the preview limit. Inspect the complete response.",
      response_preview_truncated: true,
    };
    vi.mocked(listCacheEntries).mockImplementation(async (params) =>
      successfulPage([truncatedEntry], params),
    );
    vi.mocked(getCacheEntry).mockResolvedValue({
      ok: true,
      data: {
        ...truncatedEntry,
        response: completeMarkdown,
      },
    });

    const { container } = renderInspector();

    const disclosure = await screen.findByRole("button", {
      name: "Inspect complete response",
    });
    expect(disclosure.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("Bold crossing the old boundary")).toBeNull();

    fireEvent.click(disclosure);

    const bold = await screen.findByText("Bold crossing the old boundary");
    expect(bold.tagName).toBe("STRONG");
    expect(screen.getByText("Italic evidence").tagName).toBe("EM");
    expect(screen.getByText("First complete item").closest("ul")).not.toBeNull();
    expect(screen.getByText("inlineValue").tagName).toBe("CODE");
    expect(
      screen.getByRole("link", { name: "safe link" }).getAttribute("href"),
    ).toBe("https://example.com/cache");
    expect(
      screen.getByText("const complete = true;").closest("pre"),
    ).not.toBeNull();
    expect(screen.getByText("Plain text remains readable.")).toBeTruthy();
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain('<script>alert("unsafe")</script>');
    expect(disclosure.getAttribute("aria-expanded")).toBe("true");
    expect(getCacheEntry).toHaveBeenCalledWith(
      alphaEntry.cache_key,
      expect.any(AbortSignal),
    );

    fireEvent.click(disclosure);
    expect(screen.queryByText("Bold crossing the old boundary")).toBeNull();
    expect(disclosure.getAttribute("aria-expanded")).toBe("false");
  });

  it("searches cached prompts through the inspector API", async () => {
    vi.mocked(listCacheEntries).mockImplementation(async (params) => {
      const items = params.search.toLowerCase().includes("semantic")
        ? [alphaEntry]
        : [alphaEntry, betaEntry];
      return successfulPage(items, params);
    });

    renderInspector();
    expect(await screen.findByText(betaEntry.prompt)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Search cached prompts"), {
      target: { value: "semantic" },
    });

    await waitFor(() => {
      expect(listCacheEntries).toHaveBeenCalledWith(
        {
          offset: 0,
          limit: 10,
          namespace: "",
          search: "semantic",
          sort: "newest",
        },
        expect.any(AbortSignal),
      );
    });
    expect(await screen.findByText(alphaEntry.prompt)).toBeTruthy();
    expect(screen.queryByText(betaEntry.prompt)).toBeNull();
  });

  it("restores filters and page state from the Cache URL", async () => {
    vi.mocked(listCacheEntries).mockImplementation(async (params) =>
      successfulPage([alphaEntry], params),
    );

    renderInspector(
      vi.fn(),
      "/cache?namespace=tenant-alpha&search=semantic&sort=oldest&offset=10",
    );

    await waitFor(() => {
      expect(listCacheEntries).toHaveBeenCalledWith(
        {
          offset: 10,
          limit: 10,
          namespace: "tenant-alpha",
          search: "semantic",
          sort: "oldest",
        },
        expect.any(AbortSignal),
      );
    });
    expect(
      (screen.getByLabelText("Search cached prompts") as HTMLInputElement)
        .value,
    ).toBe("semantic");
    expect(
      (await screen.findByRole("link", { name: "View entry details" }))
        .getAttribute("href"),
    ).toBe(`/cache/entries/${alphaEntry.cache_key}`);
  });

  it("filters and clears one namespace", async () => {
    let items = [alphaEntry, betaEntry];
    vi.mocked(listCacheEntries).mockImplementation(async (params) => {
      const filtered = params.namespace === ""
        ? items
        : items.filter((entry) => entry.namespace === params.namespace);
      return successfulPage(filtered, params);
    });
    vi.mocked(clearCache).mockImplementation(async (namespace) => {
      items = items.filter((entry) => entry.namespace !== namespace);
      return { ok: true, data: { cleared: true } };
    });

    renderInspector();
    await screen.findByText(alphaEntry.prompt);

    fireEvent.change(screen.getByLabelText("Namespace"), {
      target: { value: "tenant-alpha" },
    });

    await waitFor(() => {
      expect(listCacheEntries).toHaveBeenCalledWith(
        expect.objectContaining({ namespace: "tenant-alpha" }),
        expect.any(AbortSignal),
      );
    });
    expect(await screen.findByText(alphaEntry.prompt)).toBeTruthy();
    expect(screen.queryByText(betaEntry.prompt)).toBeNull();

    fireEvent.click(
      screen.getByRole("button", { name: "Clear namespace" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm clear cache" }),
    );

    await waitFor(() => {
      expect(clearCache).toHaveBeenCalledWith("tenant-alpha");
    });
    expect(await screen.findByText("The cache is empty.")).toBeTruthy();
  });

  it("requests every supported sort mode", async () => {
    vi.mocked(listCacheEntries).mockImplementation(async (params) =>
      successfulPage([alphaEntry, betaEntry], params),
    );
    renderInspector();
    await screen.findByText(alphaEntry.prompt);

    const sortSelect = screen.getByLabelText("Sort cache entries");
    const sorts = ["oldest", "most_hit", "nearest_expiry"] as const;

    expect(listCacheEntries).toHaveBeenCalledWith(
      expect.objectContaining({ sort: "newest" }),
      expect.any(AbortSignal),
    );

    for (const sort of sorts) {
      fireEvent.change(sortSelect, { target: { value: sort } });
      await waitFor(() => {
        expect(listCacheEntries).toHaveBeenCalledWith(
          expect.objectContaining({ sort }),
          expect.any(AbortSignal),
        );
      });
    }
  });

  it("confirms a single delete and refreshes the listing", async () => {
    let items = [alphaEntry];
    vi.mocked(listCacheEntries).mockImplementation(async (params) =>
      successfulPage(items, params),
    );
    vi.mocked(deleteCacheEntry).mockImplementation(async (cacheKey) => {
      items = [];
      return {
        ok: true,
        data: { deleted: true, cache_key: cacheKey },
      };
    });
    const onMutation = vi.fn();
    renderInspector(onMutation);
    await screen.findByText(alphaEntry.prompt);

    fireEvent.click(
      screen.getByRole("button", { name: `Delete ${alphaEntry.prompt}` }),
    );
    expect(deleteCacheEntry).not.toHaveBeenCalled();
    expect(
      screen.getByRole("group", {
        name: `Confirm deletion of ${alphaEntry.prompt}`,
      }),
    ).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", {
        name: `Confirm delete ${alphaEntry.prompt}`,
      }),
    );

    await waitFor(() => {
      expect(deleteCacheEntry).toHaveBeenCalledWith(alphaEntry.cache_key);
      expect(onMutation).toHaveBeenCalledWith("delete");
    });
    expect(await screen.findByText("The cache is empty.")).toBeTruthy();
    expect(
      vi.mocked(listCacheEntries).mock.calls.length,
    ).toBeGreaterThan(1);
  });

  it("confirms clear-all and refreshes after the mutation", async () => {
    let items = [alphaEntry, betaEntry];
    vi.mocked(listCacheEntries).mockImplementation(async (params) =>
      successfulPage(items, params),
    );
    vi.mocked(clearCache).mockImplementation(async () => {
      items = [];
      return { ok: true, data: { cleared: true } };
    });
    const onMutation = vi.fn();
    renderInspector(onMutation);
    await screen.findByText(alphaEntry.prompt);

    fireEvent.click(
      screen.getByRole("button", { name: "Clear all entries" }),
    );
    expect(clearCache).not.toHaveBeenCalled();
    expect(
      screen.getByRole("group", { name: "Confirm clear cache" }),
    ).toBeTruthy();

    fireEvent.click(
      screen.getByRole("button", { name: "Confirm clear cache" }),
    );

    await waitFor(() => {
      expect(clearCache).toHaveBeenCalledTimes(1);
      expect(onMutation).toHaveBeenCalledWith("clear");
    });
    expect(await screen.findByText("The cache is empty.")).toBeTruthy();
    expect(
      vi.mocked(listCacheEntries).mock.calls.length,
    ).toBeGreaterThan(1);
  });

  it("reuses a fresh cache-entry page when the inspector remounts", async () => {
    vi.mocked(listCacheEntries).mockImplementation(async (params) =>
      successfulPage([alphaEntry], params),
    );

    const first = renderInspector();
    await screen.findByText(alphaEntry.prompt);
    expect(listCacheEntries).toHaveBeenCalledOnce();
    first.unmount();

    const second = renderInspector();
    expect(screen.getByText(alphaEntry.prompt)).toBeTruthy();
    expect(
      screen.queryByLabelText("Loading cache entries"),
    ).toBeNull();
    expect(listCacheEntries).toHaveBeenCalledOnce();
    second.unmount();
  });

  it("keeps stale entries visible during one background refresh", async () => {
    const params: CacheEntryListParams = {
      offset: 0,
      limit: 10,
      namespace: "",
      search: "",
      sort: "newest",
    };
    queryClient.setQueryData(
      cacheEntryKeys.list(params),
      successfulPage([alphaEntry], params).data,
      { updatedAt: Date.now() - 20_001 },
    );
    const refresh =
      deferred<Awaited<ReturnType<typeof listCacheEntries>>>();
    vi.mocked(listCacheEntries).mockReturnValue(refresh.promise);

    renderInspector();

    expect(screen.getByText(alphaEntry.prompt)).toBeTruthy();
    expect(
      screen.queryByLabelText("Loading cache entries"),
    ).toBeNull();
    await waitFor(() => expect(listCacheEntries).toHaveBeenCalledOnce());
    expect(
      screen.getByRole("button", { name: "Refreshing" })
        .getAttribute("aria-busy"),
    ).toBe("true");

    refresh.resolve(successfulPage([betaEntry], params));
    expect(await screen.findByText(betaEntry.prompt)).toBeTruthy();
  });

  it("aborts an entry-list request when its last consumer unmounts", async () => {
    const request =
      deferred<Awaited<ReturnType<typeof listCacheEntries>>>();
    vi.mocked(listCacheEntries).mockReturnValue(request.promise);

    const inspector = renderInspector();
    await waitFor(() => expect(listCacheEntries).toHaveBeenCalledOnce());
    const signal = vi.mocked(listCacheEntries).mock.calls[0]?.[1];

    inspector.unmount();

    expect(signal?.aborted).toBe(true);
  });

  it("invalidates entry lists after deletion without touching datasets", async () => {
    const otherParams: CacheEntryListParams = {
      offset: 10,
      limit: 10,
      namespace: "tenant-alpha",
      search: "semantic",
      sort: "oldest",
    };
    const otherKey = cacheEntryKeys.list(otherParams);
    const datasetKey = benchmarkDatasetKeys.catalog();
    const detailKey = cacheEntryKeys.detail(alphaEntry.cache_key);
    queryClient.setQueryData(
      otherKey,
      successfulPage([alphaEntry], otherParams).data,
    );
    queryClient.setQueryData(datasetKey, { catalog: "unchanged" });
    queryClient.setQueryData(detailKey, {
      ...alphaEntry,
      response: alphaEntry.response_preview,
    });
    vi.mocked(listCacheEntries).mockImplementation(async (params) =>
      successfulPage([alphaEntry], params),
    );

    renderInspector();
    await screen.findByText(alphaEntry.prompt);
    fireEvent.click(
      screen.getByRole("button", { name: `Delete ${alphaEntry.prompt}` }),
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: `Confirm delete ${alphaEntry.prompt}`,
      }),
    );

    await waitFor(() => expect(deleteCacheEntry).toHaveBeenCalledOnce());
    expect(queryClient.getQueryState(otherKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryData(detailKey)).toBeUndefined();
    expect(queryClient.getQueryState(datasetKey)?.isInvalidated).toBe(false);
  });

  it("invalidates every entry list after a cache clear", async () => {
    const otherParams: CacheEntryListParams = {
      offset: 10,
      limit: 10,
      namespace: "tenant-beta",
      search: "",
      sort: "most_hit",
    };
    const otherKey = cacheEntryKeys.list(otherParams);
    const detailKey = cacheEntryKeys.detail(betaEntry.cache_key);
    queryClient.setQueryData(
      otherKey,
      successfulPage([betaEntry], otherParams).data,
    );
    queryClient.setQueryData(detailKey, {
      ...betaEntry,
      response: betaEntry.response_preview,
    });
    vi.mocked(listCacheEntries).mockImplementation(async (params) =>
      successfulPage([alphaEntry], params),
    );

    renderInspector();
    await screen.findByText(alphaEntry.prompt);
    fireEvent.click(
      screen.getByRole("button", { name: "Clear all entries" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Confirm clear cache" }),
    );

    await waitFor(() => expect(clearCache).toHaveBeenCalledOnce());
    expect(queryClient.getQueryState(otherKey)?.isInvalidated).toBe(true);
    expect(queryClient.getQueryData(detailKey)).toBeUndefined();
  });
});

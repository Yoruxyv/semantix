import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const CACHE_KEY = "a".repeat(64);
const VIEWPORTS = [
  { name: "minimum", width: 320, height: 720 },
  { name: "tablet-744", width: 744, height: 1_024 },
  { name: "tablet-768", width: 768, height: 1_024 },
  { name: "tablet-820", width: 820, height: 1_180 },
  { name: "tablet-834", width: 834, height: 1_194 },
  { name: "landscape-1133", width: 1_133, height: 744 },
  { name: "landscape-1366", width: 1_366, height: 768 },
  { name: "desktop-1024", width: 1_024, height: 900 },
  { name: "desktop-1280", width: 1_280, height: 900 },
  { name: "zoom-200-equivalent-at-1280", width: 640, height: 900 },
] as const;
const RESPONSE_PREVIEW =
  "Response exceeds the preview limit. Inspect the complete response.";
const COMPLETE_RESPONSE = [
  `${"long-content-".repeat(35)} **Complete bold response**`,
  "",
  "*Complete italic response*",
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
  '<script>alert("unsafe")</script>',
].join("\n");

test.beforeEach(async ({ page }) => {
  await page.route("**/api/v1/auth/config", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: { authentication_required: false },
    });
  });
  await page.route("**/api/v1/cache/stats**", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: { size: 1, hits: 1, misses: 0, hit_rate: 1 },
    });
  });
  await page.route("**/api/v1/cache/threshold", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: { threshold: 0.92 },
    });
  });
  await page.route("**/api/v1/cache/entries?*", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      json: {
        items: [
          {
            cache_key: CACHE_KEY,
            namespace: "default",
            prompt: "Inspect a long Markdown response",
            response_preview: RESPONSE_PREVIEW,
            response_preview_truncated: true,
            response: null,
            created_at: "2026-08-01T12:00:00Z",
            expires_at: null,
            remaining_ttl_seconds: null,
            hit_count: 1,
            last_accessed_at: "2026-08-01T12:05:00Z",
            recency_rank: 1,
            is_expired: false,
          },
        ],
        total: 1,
        offset: 0,
        limit: 10,
        has_more: false,
      },
    });
  });
  await page.route(
    `**/api/v1/cache/entries/${CACHE_KEY}`,
    async (route) => {
      await route.fulfill({
        contentType: "application/json",
        json: {
          cache_key: CACHE_KEY,
          namespace: "default",
          prompt: "Inspect a long Markdown response",
          response_preview: RESPONSE_PREVIEW,
          response_preview_truncated: true,
          response: COMPLETE_RESPONSE,
          created_at: "2026-08-01T12:00:00Z",
          expires_at: null,
          remaining_ttl_seconds: null,
          hit_count: 1,
          last_accessed_at: "2026-08-01T12:05:00Z",
          recency_rank: 1,
          is_expired: false,
        },
      });
    },
  );
});

for (const viewport of VIEWPORTS) {
  test(`complete cache Markdown is accessible without overflow at ${viewport.name}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto("/cache");

    const disclosure = page.getByRole("button", {
      name: "Inspect complete response",
    });
    await expect(disclosure).toBeVisible();
    await disclosure.focus();
    await disclosure.press("Enter");

    await expect(
      page.getByText("Complete bold response"),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Hide complete response" }),
    ).toHaveAttribute("aria-expanded", "true");
    await expect(
      page.getByRole("link", { name: "safe link" }),
    ).toHaveAttribute("href", "https://example.com/cache");
    await expect(page.locator("main script")).toHaveCount(0);
    await expect(page.getByText('<script>alert("unsafe")</script>')).toBeVisible();

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);

    const accessibility = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();
    expect(accessibility.violations).toEqual([]);
  });

  test(`cache entry detail is accessible without overflow at ${viewport.name}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto(`/cache/entries/${CACHE_KEY}`);

    await expect(
      page.getByRole("heading", { name: "Cache entry detail" }),
    ).toBeVisible();
    if (viewport.width < 1_024) {
      await page.getByRole("button", { name: "Open primary menu" }).click();
    }
    await expect(
      page.getByRole("link", { name: "Cache", exact: true }),
    ).toHaveAttribute("aria-current", "page");
    await expect(page.getByText(RESPONSE_PREVIEW)).toBeVisible();
    await expect(page.getByText("Complete bold response")).toHaveCount(0);
    await expect(page.getByText(CACHE_KEY)).toBeVisible();

    const columns = await page
      .locator("[data-cache-entry-detail-grid]")
      .evaluate((element) => getComputedStyle(element).gridTemplateColumns);
    if (viewport.width < 1_024) {
      expect(columns.split(" ")).toHaveLength(1);
    }

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);

    const accessibility = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"])
      .analyze();
    expect(accessibility.violations).toEqual([]);
  });
}

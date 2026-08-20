import AxeBuilder from "@axe-core/playwright";
import {
  expect,
  test,
  type Page,
} from "@playwright/test";

const COMPACT_VIEWPORTS = [
  { name: "phone", width: 320, height: 720 },
  { name: "744 portrait", width: 744, height: 1024 },
  { name: "768 portrait", width: 768, height: 1024 },
  { name: "820 portrait", width: 820, height: 1180 },
  { name: "834 portrait", width: 834, height: 1194 },
] as const;

const EXPANDED_VIEWPORTS = [
  { name: "1024 desktop", width: 1024, height: 900 },
  { name: "1280 desktop", width: 1280, height: 900 },
  { name: "744 landscape", width: 1133, height: 744 },
  { name: "768 landscape", width: 1366, height: 768 },
  { name: "820 landscape", width: 1180, height: 820 },
  { name: "834 landscape", width: 1194, height: 834 },
] as const;

const NAVIGATION_LABELS = [
  "Monitor",
  "Cache",
  "Evaluations",
  "Observability",
] as const;

async function installApiFixtures(page: Page): Promise<void> {
  await page.route("**/api/v1/auth/config", async (route) => {
    await route.fulfill({
      json: { authentication_required: false },
    });
  });
  await page.route("**/api/v1/cache/stats**", async (route) => {
    await route.fulfill({
      json: { size: 0, hits: 0, misses: 0, hit_rate: 0 },
    });
  });
  await page.route("**/api/v1/cache/threshold", async (route) => {
    await route.fulfill({ json: { threshold: 0.9 } });
  });
  await page.route("**/api/v1/evaluations/datasets", async (route) => {
    await route.fulfill({
      json: {
        datasets: [
          {
            dataset_id: "quick",
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
  });
}

async function openEvaluationWorkspace(page: Page): Promise<void> {
  await page.goto("/evaluations");
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Evaluation laboratory",
    }),
  ).toBeVisible();
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
}

async function expectSharedRouteContract(page: Page): Promise<void> {
  await expect(page).toHaveTitle("Evaluations | Semantix");
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(
    page.locator('#primary-navigation a[href="/evaluations"]'),
  ).toHaveAttribute("aria-current", "page");
  await expect(
    page.locator("#primary-navigation a"),
  ).toHaveCount(NAVIGATION_LABELS.length);
  await expectNoHorizontalOverflow(page);

  const accessibility = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa"])
    .analyze();
  expect(accessibility.violations).toEqual([]);
}

for (const viewport of COMPACT_VIEWPORTS) {
  test(`compact navigation is accessible at ${viewport.name}`, async ({
    page,
  }) => {
    await installApiFixtures(page);
    await page.setViewportSize(viewport);
    await openEvaluationWorkspace(page);

    const navigation = page.getByRole("navigation", {
      name: "Primary navigation",
    });
    const menuButton = page.getByRole("button", {
      name: "Open primary menu",
    });
    await expect(navigation).toBeHidden();
    await expect(menuButton).toBeVisible();
    const buttonBox = await menuButton.boundingBox();
    expect(buttonBox?.width).toBeGreaterThanOrEqual(44);
    expect(buttonBox?.height).toBeGreaterThanOrEqual(44);

    await menuButton.press("Enter");
    await expect(navigation).toBeVisible();
    for (const label of NAVIGATION_LABELS) {
      await page.keyboard.press("Tab");
      await expect(page.getByRole("link", { name: label })).toBeFocused();
    }

    await page.keyboard.press("Escape");
    await expect(navigation).toBeHidden();
    await expect(menuButton).toBeFocused();

    await menuButton.press("Space");
    await expect(navigation).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(navigation).toBeHidden();
    await expectSharedRouteContract(page);
  });
}

for (const viewport of EXPANDED_VIEWPORTS) {
  test(`expanded navigation is accessible at ${viewport.name}`, async ({
    page,
  }) => {
    await installApiFixtures(page);
    await page.setViewportSize(viewport);
    await openEvaluationWorkspace(page);

    await expect(
      page.getByRole("navigation", { name: "Primary navigation" }),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Open primary menu" }),
    ).toBeHidden();
    const navigation = page.getByRole("navigation", {
      name: "Primary navigation",
    });
    const navigationBox = await navigation.boundingBox();
    const lastLinkBox = await navigation
      .getByRole("link", { name: "Observability" })
      .boundingBox();
    expect(navigationBox).not.toBeNull();
    expect(lastLinkBox).not.toBeNull();
    expect(
      navigationBox!.x +
        navigationBox!.width -
        (lastLinkBox!.x + lastLinkBox!.width),
    ).toBeLessThanOrEqual(6);

    const headerRowBox = await navigation.locator("..").boundingBox();
    const uptimeBox = await page
      .getByText("Session uptime", { exact: true })
      .locator("..")
      .boundingBox();
    expect(headerRowBox).not.toBeNull();
    expect(uptimeBox).not.toBeNull();
    expect(
      Math.abs(
        navigationBox!.x +
          navigationBox!.width / 2 -
          (headerRowBox!.x + headerRowBox!.width / 2),
      ),
    ).toBeLessThanOrEqual(1);
    expect(
      headerRowBox!.x +
        headerRowBox!.width -
        (uptimeBox!.x + uptimeBox!.width),
    ).toBeLessThanOrEqual(1);
    await expectSharedRouteContract(page);
  });
}

test("legacy route replaces history and preserves query and hash", async ({
  page,
}) => {
  await installApiFixtures(page);
  await page.setViewportSize({ width: 820, height: 1180 });
  await page.goto("/");
  await page.goto("/benchmarks?dataset=quick#results");

  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Evaluation laboratory",
    }),
  ).toBeVisible();
  await expect(page).toHaveURL(/\/evaluations\?dataset=quick#results$/);
  await expect(page.getByRole("main")).toBeFocused();

  await page.goBack();
  await expect(page).toHaveURL(/\/$/);
});

test("compact menu closes on routing and expanded resize cleanup", async ({
  page,
}) => {
  await installApiFixtures(page);
  await page.setViewportSize({ width: 820, height: 1180 });
  await openEvaluationWorkspace(page);

  await page.getByRole("button", { name: "Open primary menu" }).click();
  await page.getByRole("link", { name: "Cache" }).click();
  await expect(page).toHaveURL(/\/cache$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Cache inspector" }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Open primary menu" }),
  ).toHaveAttribute("aria-expanded", "false");

  await page.getByRole("button", { name: "Open primary menu" }).click();
  await page.setViewportSize({ width: 1024, height: 900 });
  await expect(
    page.getByRole("navigation", { name: "Primary navigation" }),
  ).toBeVisible();
  await page.setViewportSize({ width: 820, height: 1180 });
  await expect
    .poll(() => page.evaluate(() => window.innerWidth))
    .toBe(820);
  const compactMenuButton = page.getByRole("button", {
    name: "Open primary menu",
  });
  await expect(compactMenuButton).toHaveAttribute("aria-expanded", "false");
  await expect(
    page.getByRole("navigation", { name: "Primary navigation" }),
  ).toBeHidden();
});

test("zoom-equivalent, increased-text, and long-label layouts do not overflow", async ({
  page,
}) => {
  await installApiFixtures(page);

  await page.setViewportSize({ width: 640, height: 900 });
  await openEvaluationWorkspace(page);
  await expect(
    page.getByRole("button", { name: "Open primary menu" }),
  ).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.evaluate(() => {
    document.documentElement.style.fontSize = "125%";
  });
  await expectNoHorizontalOverflow(page);

  await page.evaluate(() => {
    document.documentElement.style.fontSize = "";
  });
  await page.setViewportSize({ width: 1024, height: 900 });
  await page
    .getByRole("link", { name: "Evaluations" })
    .evaluate((element) => {
      element.textContent = "Evaluation quality analysis";
    });
  await expectNoHorizontalOverflow(page);
});

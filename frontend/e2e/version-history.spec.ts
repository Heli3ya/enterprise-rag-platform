import { expect, test, type Page } from "@playwright/test";

/**
 * Subtask 3 — the Version History dialog.
 *
 * Only the GET chain is mocked; the Django suite already proves the chain
 * is archived and indexed correctly. Here we prove the UI asks for it and
 * renders both the superseded and the current version.
 */

const FAKE_TOKEN = "eyJhbGciOiJub25lIn0.eyJleHAiOjQwMDAwMDAwMDB9.signature";

const row = {
  id: 5,
  title: "Supply contract",
  department: 1,
  status: "Indexed",
  created_at: "2026-11-16T09:00:00Z",
  is_system: false,
  version: 2,
  parent_document: 4,
};

const history = {
  document_id: 5,
  version: 2,
  latest_document_id: 5,
  versions: [
    {
      id: 4,
      version: 1,
      title: "Supply contract",
      status: "Archived",
      file_size: 2048,
      created_at: "2026-11-01T09:00:00Z",
      archived_at: "2026-11-16T09:00:00Z",
      purged_at: null,
      is_current: false,
    },
    {
      id: 5,
      version: 2,
      title: "Supply contract",
      status: "Indexed",
      file_size: 4096,
      created_at: "2026-11-16T09:00:00Z",
      archived_at: null,
      purged_at: null,
      is_current: true,
    },
  ],
};

async function mockWorkspace(
  page: Page,
  historyResponse: { status: number; body: unknown } = { status: 200, body: history },
) {
  await page.addInitScript((token) => {
    localStorage.setItem("access_token", token);
    localStorage.setItem("refresh_token", "e2e-refresh-token");
  }, FAKE_TOKEN);

  await page.route(/\/auth\/me\/?/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        username: "e2e-member",
        role: "Member",
        department_id: 1,
        department_name: "IT",
        tenant_id: 1,
        tenant_name: "E2E Org",
      }),
    }),
  );

  await page.route(/\/departments\/readiness\//, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        department_id: 1,
        department_name: "IT",
        document_count: 1,
        has_searchable_content: true,
        is_empty: false,
        onboarding_document_id: null,
      }),
    }),
  );

  await page.route(/\/departments\/$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{ id: 1, name: "IT" }]),
    }),
  );

  await page.route(/\/documents\/$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([row]),
    }),
  );

  await page.route(/\/documents\/\d+\/versions\//, (route) =>
    route.fulfill({
      status: historyResponse.status,
      contentType: "application/json",
      body: JSON.stringify(historyResponse.body),
    }),
  );
}

test("the history dialog shows archived and current versions", async ({
  page,
}) => {
  const historyCalls: string[] = [];

  await mockWorkspace(page);
  await page.route(/\/documents\/\d+\/versions\//, (route) => {
    historyCalls.push(`${route.request().method()} ${new URL(route.request().url()).pathname}`);
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(history),
    });
  });

  await page.goto("/");
  // A cold Next dev server can take longer than the default 5s assertion
  // timeout to compile the page, so wait for the mocked document explicitly.
  await page.getByText("Supply contract").waitFor({ timeout: 20000 });

  const tableRow = page.getByRole("row", { name: /Supply contract/ });
  await expect(tableRow.getByTestId("document-version-count")).toHaveText(
    "2 versions",
  );

  // Both the count chip and the row action open the same dialog.
  await tableRow.getByTestId("document-version-history").click();

  const dialog = page.getByRole("dialog", { name: "Version history" });
  await expect(dialog).toBeVisible();
  await expect
    .poll(() => historyCalls.at(-1))
    .toBe("GET /api/documents/5/versions/");

  const entries = dialog.getByTestId("version-history-row");
  await expect(entries).toHaveCount(2);
  await expect(entries.nth(0)).toContainText("v1");
  await expect(entries.nth(0)).toContainText("Archived");
  await expect(entries.nth(1)).toContainText("v2");
  await expect(entries.nth(1)).toContainText("Indexed");
  await expect(dialog.getByTestId("version-history-current")).toHaveText(
    "Current",
  );

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
});

test("the count chip opens the same history view", async ({ page }) => {
  await mockWorkspace(page);
  await page.goto("/");
  // A cold Next dev server can take longer than the default 5s assertion
  // timeout to compile the page, so wait for the mocked document explicitly.
  await page.getByText("Supply contract").waitFor({ timeout: 20000 });

  await page.getByTestId("document-version-count").click();

  await expect(
    page.getByRole("dialog", { name: "Version history" }),
  ).toBeVisible();
});

test("a failed history request is reported inside the dialog", async ({
  page,
}) => {
  await mockWorkspace(page, {
    status: 500,
    body: { detail: "History is temporarily unavailable." },
  });
  await page.goto("/");
  // A cold Next dev server can take longer than the default 5s assertion
  // timeout to compile the page, so wait for the mocked document explicitly.
  await page.getByText("Supply contract").waitFor({ timeout: 20000 });

  await page.getByTestId("document-version-history").click();

  await expect(
    page.getByRole("dialog", { name: "Version history" }).getByRole("alert"),
  ).toContainText("History is temporarily unavailable.");
});

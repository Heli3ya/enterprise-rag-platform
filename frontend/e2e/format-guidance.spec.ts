import { expect, test, type Page } from "@playwright/test";

/**
 * Subtask 1 — the drop zone must *show* what the backend accepts.
 *
 * The chips, the `accept` attribute and the JavaScript gate all come from
 * one catalogue. This spec checks the rendered result so a future edit that
 * reintroduces a second, hardcoded list is caught in the browser.
 */

const FAKE_TOKEN = "eyJhbGciOiJub25lIn0.eyJleHAiOjQwMDAwMDAwMDB9.signature";

async function mockWorkspace(page: Page) {
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
        document_count: 0,
        has_searchable_content: false,
        is_empty: true,
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
      body: JSON.stringify([]),
    }),
  );
}

test("the drop zone advertises every supported format family", async ({
  page,
}) => {
  await mockWorkspace(page);
  await page.goto("/");

  const guide = page.getByTestId("upload-format-guide");

  await expect(guide).toBeVisible();
  for (const key of ["pdf", "word", "text", "excel", "email", "image"]) {
    await expect(page.getByTestId(`upload-format-${key}`)).toBeVisible();
  }

  await expect(guide).toContainText("Excel / CSV");
  await expect(guide).toContainText("Email");
  await expect(guide).toContainText("Images");
  await expect(
    page.getByText(
      "Spreadsheets, emails and scanned images are indexed and searchable too.",
    ),
  ).toBeVisible();

  const accept = await page
    .getByLabel("Choose a document file")
    .getAttribute("accept");

  for (const extension of [
    ".xlsx",
    ".csv",
    ".eml",
    ".jpg",
    ".jpeg",
    ".png",
  ]) {
    expect(accept).toContain(extension);
  }
});

test("an email file is accepted while an unsupported image is rejected", async ({
  page,
}) => {
  await mockWorkspace(page);
  await page.goto("/");

  const picker = page.getByLabel("Choose a document file");

  await picker.setInputFiles({
    name: "invoice.eml",
    mimeType: "message/rfc822",
    buffer: Buffer.from("From: a@example.com\r\nSubject: Invoice\r\n\r\nBody"),
  });

  await expect(page.getByText("invoice.eml")).toBeVisible();

  await picker.setInputFiles({
    name: "animation.gif",
    mimeType: "image/gif",
    buffer: Buffer.from("GIF89a"),
  });

  await expect(
    page.getByRole("alert").getByText(
      "Only PDF, Word (.doc/.docx), TXT, Excel (.xlsx), CSV, EML, JPG, and PNG files are allowed.",
    ),
  ).toBeVisible();
});

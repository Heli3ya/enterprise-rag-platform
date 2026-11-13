import { test, expect, type Page } from "@playwright/test";

/**
 * Cold start, in the browser.
 *
 * Three things must be true for a department that has no documents:
 *   1. the dashboard says so up front, with a large way out,
 *   2. asking a question produces an explanation instead of a made-up
 *      answer (and offers nothing to rate),
 *   3. uploading the first file removes the empty state without a
 *      reload.
 *
 * The backend is fully mocked; `readinessState` is mutated by the
 * upload handler so the refresh after an upload returns a different
 * answer, exactly like the real endpoint would.
 */

const GUIDE_ID = 41;

async function mockSignedInSurface(
  page: Page,
  options: { isEmpty: boolean },
) {
  const readinessState = { isEmpty: options.isEmpty };

  await page.route(/\/auth\/login\/?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access: "eyJhbGciOiJub25lIn0.eyJleHAiOjQwMDAwMDAwMDB9.signature",
        refresh: "e2e-refresh-token",
      }),
    });
  });

  await page.route(/\/auth\/me\/?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 2,
        username: "e2e-member",
        role: "Member",
        department_id: 1,
        department_name: "IT",
      }),
    });
  });

  await page.route(/\/departments\/readiness\/?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        department_id: 1,
        department_name: "IT",
        document_count: readinessState.isEmpty ? 0 : 1,
        has_searchable_content: true,
        is_empty: readinessState.isEmpty,
        onboarding_document_id: GUIDE_ID,
      }),
    });
  });

  await page.route(/\/departments\/?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{ id: 1, name: "IT" }]),
    });
  });

  await page.route(/\/documents\/?$/, async (route) => {
    if (route.request().method() === "POST") {
      readinessState.isEmpty = false;

      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ document_id: 7, status: "Pending" }),
      });

      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([
        {
          id: GUIDE_ID,
          title: "راهنمای شروع به کار دپارتمان «IT»",
          department: 1,
          status: "Indexed",
          created_at: "2026-11-12T09:00:00Z",
          is_system: true,
        },
      ]),
    });
  });

  // No documents, no tokens: the backend stops before the LLM.
  await page.route(/\/chat\/ask\/?$/, async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
      },
      body:
        'event: meta\ndata: {"answer_id":null,"conversation_id":"cold-e2e"}\n\n' +
        'event: no_documents\ndata: {"reason":"empty_department","message":"در حال حاضر سندی مرتبط با این موضوع در دپارتمان شما یافت نشد"}\n\n' +
        "event: done\ndata: {}\n\n",
    });
  });

  return readinessState;
}

async function signIn(page: Page) {
  await page.goto("/login");

  await page.getByLabel("Username").fill("e2e-member");
  await page.getByLabel("Password").fill("E2E-test-password");
  await page.getByRole("button", { name: "Login" }).click();

  await expect(page).toHaveURL(/\/$/, { timeout: 15000 });
}

test("an empty department shows the cold-start state with a large upload action", async ({
  page,
}) => {
  await mockSignedInSurface(page, { isEmpty: true });
  await signIn(page);

  await expect(
    page.getByRole("heading", { name: "Your department has no documents yet" }),
  ).toBeVisible();

  const upload = page.getByRole("button", {
    name: "Upload your first document",
  });

  await expect(upload).toBeVisible();

  // The secondary action keeps the assistant reachable: the guide can
  // already answer "how do I use this?".
  await expect(
    page.getByRole("button", {
      name: "Ask the assistant how to use the platform",
    }),
  ).toBeVisible();

  await upload.click();

  // Focus lands on the uploader's drop zone, not on a random element.
  await expect(page.locator("#document-upload-trigger")).toBeFocused();
});

test("a question in an empty department explains itself and offers no rating", async ({
  page,
}) => {
  await mockSignedInSurface(page, { isEmpty: true });
  await signIn(page);

  await page
    .getByPlaceholder("Type your question...")
    .fill("What is the parental leave policy?");

  await page.getByRole("button", { name: "Send" }).click();

  // The inline empty state is the only status region on the page.
  const notice = page.getByRole("status");

  await expect(notice).toContainText("Your department has no documents yet");
  await expect(notice).toContainText(
    "Upload the first one, or ask how the platform works.",
  );

  await expect(
    notice.getByRole("button", { name: "Upload your first document" }),
  ).toBeVisible();

  // Nothing was generated, so nothing may be rated.
  await expect(page.getByRole("button", { name: "Helpful" })).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Not helpful" }),
  ).toHaveCount(0);
});

test("the empty state disappears after the first upload, without a reload", async ({
  page,
}) => {
  await mockSignedInSurface(page, { isEmpty: true });
  await signIn(page);

  await expect(
    page.getByRole("heading", { name: "Your department has no documents yet" }),
  ).toBeVisible();

  await page.setInputFiles('input[type="file"]', {
    name: "policy.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Annual leave is 20 days per year."),
  });

  // `exact` matters here: the cold-start card is labelled "Your department
  // has no documents yet", so a loose getByLabel("Department") matches both
  // the card and the select.
  await page.getByLabel("Department", { exact: true }).selectOption("1");
  await page.getByRole("button", { name: "Upload Document" }).click();

  await expect(page.getByText("Document uploaded successfully.")).toBeVisible();

  // The dashboard re-asked for readiness; no navigation happened.
  await expect(
    page.getByRole("heading", { name: "Your department has no documents yet" }),
  ).toHaveCount(0);

  await expect(page).toHaveURL(/\/$/);
});

test("a department with documents never sees the cold-start state", async ({
  page,
}) => {
  await mockSignedInSurface(page, { isEmpty: false });
  await signIn(page);

  await expect(page.getByRole("heading", { name: "Chat Assistant" })).toBeVisible();

  await expect(
    page.getByRole("heading", { name: "Your department has no documents yet" }),
  ).toHaveCount(0);

  // The system guide is listed but cannot be deleted by a user: the
  // only document in the table is the generated one.
  await expect(page.getByText("System guide")).toBeVisible();
  await expect(page.getByRole("button", { name: "Delete" })).toHaveCount(0);
});

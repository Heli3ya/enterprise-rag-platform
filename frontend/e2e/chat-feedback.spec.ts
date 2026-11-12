import { test, expect, type Page } from "@playwright/test";

/**
 * Feedback loop UI: thumbs up, thumbs down with a reason, and a server
 * failure that must leave the buttons usable again.
 *
 * The backend is fully mocked. The chat stream now starts with a `meta`
 * event carrying the answer id, which is exactly what the widget needs;
 * without it no feedback UI is rendered at all.
 */

const ANSWER_ID = "5b1f7f0e-9c2a-4a41-9f0e-2f4a1b6c7d80";
const ANSWER_TEXT = "Employees receive 20 days of annual leave.";

async function mockSignedInSurface(page: Page) {
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

  await page.route(/\/departments\/?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{ id: 1, name: "IT" }]),
    });
  });

  // The dashboard asks for department readiness on mount. Without a
  // mock this request would reach the real API and a 401 would bounce
  // the browser to /login.
  await page.route(/\/departments\/readiness\/?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        department_id: 1,
        department_name: "IT",
        document_count: 2,
        has_searchable_content: true,
        is_empty: false,
        onboarding_document_id: 41,
      }),
    });
  });

  await page.route(/\/documents\/?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  // `meta` first, then the answer. The widget stays hidden until `done`.
  await page.route(/\/chat\/ask\/?$/, async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
      },
      body:
        `event: meta\ndata: {"answer_id":"${ANSWER_ID}","conversation_id":"e2e-conv"}\n\n` +
        `event: token\ndata: ${JSON.stringify({ content: ANSWER_TEXT })}\n\n` +
        "event: done\ndata: {}\n\n",
    });
  });
}

async function signInAndAsk(page: Page) {
  await page.goto("/login");

  await page.getByLabel("Username").fill("e2e-member");
  await page.getByLabel("Password").fill("E2E-test-password");
  await page.getByRole("button", { name: "Login" }).click();

  await expect(page).toHaveURL(/\/$/, { timeout: 15000 });
  await expect(page.getByText(ANSWER_TEXT)).toHaveCount(0);

  await page
    .getByPlaceholder("Type your question...")
    .fill("How many annual leave days do employees get?");

  await page.getByRole("button", { name: "Send" }).click();

  await expect(page.getByText(ANSWER_TEXT)).toBeVisible();
}

test("thumbs down asks for a reason and sends it once", async ({ page }) => {
  const sent: Record<string, unknown>[] = [];

  await mockSignedInSurface(page);

  await page.route(/\/chat\/feedback\/?$/, async (route) => {
    sent.push(JSON.parse(route.request().postData() ?? "{}"));

    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        id: 1,
        answer_id: ANSWER_ID,
        is_positive: false,
        user_comment: "The answer ignored the department policy.",
        created_at: "2026-11-10T10:00:00Z",
      }),
    });
  });

  await signInAndAsk(page);

  // The widget appears only after the stream finished.
  const down = page.getByRole("button", { name: "Not helpful", exact: true });
  const up = page.getByRole("button", { name: "Helpful", exact: true });

  await expect(down).toBeVisible();
  await expect(up).toBeEnabled();

  // A down vote opens the reason box instead of submitting immediately.
  await down.click();

  const reason = page.getByLabel("What went wrong with this answer?");
  await expect(reason).toBeVisible();
  expect(sent).toHaveLength(0);

  await reason.fill("The answer ignored the department policy.");
  await page.getByRole("button", { name: "Submit feedback" }).click();

  await expect(page.getByText("Thanks for your feedback.")).toBeVisible();
  await expect(down).toBeDisabled();
  await expect(up).toBeDisabled();
  await expect(reason).toHaveCount(0);

  expect(sent).toHaveLength(1);
  expect(sent[0]).toEqual({
    answer_id: ANSWER_ID,
    is_positive: false,
    user_comment: "The answer ignored the department policy.",
  });

  // No reload: the conversation is still on screen.
  await expect(page.getByText(ANSWER_TEXT)).toBeVisible();
});

test("thumbs up submits in one click without a comment box", async ({
  page,
}) => {
  const sent: Record<string, unknown>[] = [];

  await mockSignedInSurface(page);

  await page.route(/\/chat\/feedback\/?$/, async (route) => {
    sent.push(JSON.parse(route.request().postData() ?? "{}"));

    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({
        id: 2,
        answer_id: ANSWER_ID,
        is_positive: true,
        user_comment: "",
        created_at: "2026-11-10T10:00:00Z",
      }),
    });
  });

  await signInAndAsk(page);

  await page.getByRole("button", { name: "Helpful", exact: true }).click();

  await expect(page.getByText("Thanks for your feedback.")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Not helpful", exact: true }),
  ).toBeDisabled();

  expect(sent).toHaveLength(1);
  expect(sent[0]).toEqual({
    answer_id: ANSWER_ID,
    is_positive: true,
    user_comment: "",
  });
});

test("a failed submission re-enables the buttons and shows an error", async ({
  page,
}) => {
  await mockSignedInSurface(page);

  await page.route(/\/chat\/feedback\/?$/, async (route) => {
    await route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({ error: "Internal server error." }),
    });
  });

  await signInAndAsk(page);

  const up = page.getByRole("button", { name: "Helpful", exact: true });

  await up.click();

  await expect(
    page.getByText("Could not send your feedback. Please try again."),
  ).toBeVisible();

  // The verdict was not stored, so the user must be able to retry.
  await expect(up).toBeEnabled();
  await expect(
    page.getByRole("button", { name: "Not helpful", exact: true }),
  ).toBeEnabled();
});


import { test, expect } from "@playwright/test";

test("member completes upload, chat, and citation flow", async ({ page }) => {
  let uploaded = false;
  let uploadRequestBody = "";

  const document = {
    id: 101,
    title: "E2E Knowledge",
    file_name: "e2e-knowledge.txt",
    filename: "e2e-knowledge.txt",
    department: 1,
    department_name: "IT",
    status: "Indexed",
    file_size: 100,
  };

  // Diagnostic logging: requests, responses, and browser errors.
  page.on("request", (request) => {
    if (request.url().includes("/api/") || request.url().includes("/auth/")) {
      console.log("[REQUEST]", request.method(), request.url());
    }
  });

  page.on("response", async (response) => {
    if (response.url().includes("/api/") || response.url().includes("/auth/")) {
      console.log("[RESPONSE]", response.status(), response.url());

      if (response.status() >= 400) {
        console.log("[ERROR BODY]", await response.text().catch(() => ""));
      }
    }
  });

  page.on("pageerror", (error) => {
    console.log("[BROWSER ERROR]", error.message);
  });

  page.on("console", (message) => {
    if (message.type() === "error") {
      console.log("[CONSOLE ERROR]", message.text());
    }
  });

  // Mock login. The response shape matches app/login/page.tsx.
  await page.route(/\/auth\/login\/?$/, async (route) => {
    console.log("[MOCK] Login matched");

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access:
          "eyJhbGciOiJub25lIn0.eyJleHAiOjQwMDAwMDAwMDB9.signature",
        refresh: "e2e-refresh-token",
      }),
    });
  });

  // Mock authenticated user.
  await page.route(/\/auth\/me\/?$/, async (route) => {
    console.log("[MOCK] User profile matched");

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

  // Mock departments.
  await page.route(/\/departments\/?$/, async (route) => {
    console.log("[MOCK] Departments matched");

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{ id: 1, name: "IT" }]),
    });
  });

  // Cold-start probe fired by the dashboard. A department with real
  // documents keeps the empty state hidden, and mocking it keeps the
  // request away from the real API (a 401 would bounce to /login).
  await page.route(/\/departments\/readiness\/?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        department_id: 1,
        department_name: "IT",
        document_count: 3,
        has_searchable_content: true,
        is_empty: false,
        onboarding_document_id: 41,
      }),
    });
  });

  // Mock document listing and upload.
  await page.route(/\/documents\/?$/, async (route) => {
    if (route.request().method() === "POST") {
      console.log("[MOCK] Document upload matched");

      const body = await route.request().postDataBuffer();
      uploadRequestBody = body?.toString("utf8") ?? "";
      uploaded = true;

      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify(document),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(uploaded ? [document] : []),
    });
  });

  // Mock the streaming chat response and citation.
  await page.route(/\/chat\/ask\/?$/, async (route) => {
    console.log("[MOCK] Chat request matched");

    await route.fulfill({
      status: 200,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
      },
      body:
        'event: token\ndata: {"content":"Documents are retained for seven years [1]."}\n\n' +
        'event: citations\ndata: [{"document_id":101,"title":"E2E Knowledge","filename":"e2e-knowledge.txt","department":"IT","chunk_id":1,"chunk_index":0,"snippet":"Example policy: documents are retained for seven years."}]\n\n' +
        "event: done\ndata: {}\n\n",
    });
  });

  // Mock the chunk detail endpoint used by the citation drawer.
  // The panel requests `/documents/chunks/1/?q=...`, so the pattern must
  // allow a query string — anchoring at `$` alone let the request escape
  // to the real backend, where the fake token answered 401.
  await page.route(/\/documents\/chunks\/\d+\/?(?:\?.*)?$/, async (route) => {
    console.log("[MOCK] Chunk detail matched");

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        chunk_id: 1,
        chunk_index: 0,
        content: "Example policy: documents are retained for seven years.",
        document_id: 101,
        document_title: "E2E Knowledge",
        filename: "e2e-knowledge.txt",
        file_type: "text/plain",
        file_url: "/documents/101/file/",
        preview_url: "/documents/101/preview/",
        department: "IT",
        department_id: 1,
        is_public: false,
        uploaded_by: "e2e-member",
        created_at: "2026-01-01T00:00:00Z",
        highlights: [[0, 7]],
        matched_terms: ["example"],
      }),
    });
  });

  // Mock the whole-document preview used by the "In the document" tab.
  await page.route(/\/documents\/\d+\/preview\/?/, async (route) => {
    console.log("[MOCK] Document preview matched");

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        document_id: 101,
        title: "E2E Knowledge",
        filename: "e2e-knowledge.txt",
        file_type: "text/plain",
        file_url: "/documents/101/file/",
        department: "IT",
        content:
          "Example policy: documents are retained for seven years.",
        highlights: [[0, 7]],
        matched_terms: ["example"],
        truncated: false,
      }),
    });
  });

  // Mock the protected original-file download.
  await page.route(/\/documents\/\d+\/file\/?$/, async (route) => {
    console.log("[MOCK] Document file matched");

    await route.fulfill({
      status: 200,
      headers: { "Content-Type": "text/plain" },
      body: "Example policy: documents are retained for seven years.",
    });
  });

  // 1. Login through the UI.
  await page.goto("/login");

  await page.getByLabel("Username").fill("e2e-member");
  await page.getByLabel("Password").fill("E2E-test-password");
  await page.getByRole("button", { name: "Login" }).click();
  console.log("[URL AFTER LOGIN]", page.url());

console.log(
  "[LOGIN ERROR]",
  await page.getByRole("alert").allTextContents(),
);

console.log(
  "[STORED TOKENS]",
  await page.evaluate(() => ({
    access: localStorage.getItem("access_token"),
    refresh: localStorage.getItem("refresh_token"),
  })),
);

  // 2. Verify successful login and protected home page.
  await expect(page).toHaveURL(/\/$/, { timeout: 15000 });

  await expect(
    page.getByRole("heading", { name: "Enterprise RAG Platform" }),
  ).toBeVisible();

  await expect(page.getByText("e2e-member")).toBeVisible();

  // 3. Select a TXT file, title, and department.
  await page.getByLabel("Choose a document file").setInputFiles({
    name: "e2e-knowledge.txt",
    mimeType: "text/plain",
    buffer: Buffer.from(
      "Example policy: documents are retained for seven years.",
    ),
  });

  await page.locator("#document-title").fill("E2E Knowledge");
  await page.locator("#document-department").selectOption("1");

  // 4. Upload and verify the result.
  await page.getByRole("button", { name: "Upload Document" }).click();

  await expect(
    page.getByRole("status").getByText("Document uploaded successfully."),
  ).toBeVisible();

  expect(uploaded).toBeTruthy();
  expect(uploadRequestBody).toContain("e2e-knowledge.txt");
  expect(uploadRequestBody).toContain("E2E Knowledge");
  expect(uploadRequestBody).toContain('name="department"');
  expect(uploadRequestBody).toContain('name="file_path"');

  // 5. Ask a question.
  await page
    .getByPlaceholder("Type your question...")
    .fill("How long are documents retained?");

  await page.getByRole("button", { name: "Send" }).click();

  // 6. Verify the answer.
  await expect(
    page.getByText("Documents are retained for seven years."),
  ).toBeVisible();

  // 7. The source list shows the cited document and its chunk.
  await expect(page.getByText("Sources", { exact: true })).toBeVisible();

  // The source card is labelled `Source [<chunk_id>] <filename>`, matching
  // the `[n]` markers inside the answer text.
  await expect(
    page.getByRole("button", { name: /Source \[1\] e2e-knowledge\.txt/ }),
  ).toBeVisible();

  await expect(page.getByText("IT · Chunk 1", { exact: true })).toBeVisible();

  // 8. Clicking the inline [1] marker opens the cited passage.
  await page.getByRole("button", { name: "Open citation [1]" }).click();

  const citationDialog = page.getByRole("dialog", { name: "Citation source" });

  await expect(citationDialog).toBeVisible();
  await expect(citationDialog.getByText("Source [1]")).toBeVisible();
  await expect(citationDialog.getByText("E2E Knowledge")).toBeVisible();

  await expect(
    citationDialog.getByText(
      "Example policy: documents are retained for seven years.",
    ),
  ).toBeVisible();

  // The whole document opens with every match highlighted.
  await expect(citationDialog.locator("mark").first()).toHaveText("Example");

  await expect(
    citationDialog.getByText("Highlighted:", { exact: false }),
  ).toBeVisible();

  // The precise retrieved chunk is still one click away.
  await citationDialog.getByRole("button", { name: "Cited passage" }).click();

  await expect(
    citationDialog.getByRole("button", { name: "Cited passage" }),
  ).toHaveAttribute("aria-pressed", "true");

  // The passage tab shows the retrieved chunk itself, not the whole file.
  await expect(
    citationDialog.getByText(
      "Example policy: documents are retained for seven years.",
      { exact: true },
    ),
  ).toBeVisible();

  await expect(
    citationDialog.getByRole("button", { name: "Open original file" }),
  ).toBeEnabled();

  // 9. The same source can be opened from the card list.
  await citationDialog.getByRole("button", { name: "Close" }).click();

  await expect(citationDialog).toHaveCount(0);

  await page
    .getByRole("button", { name: /Source \[1\] e2e-knowledge\.txt/ })
    .click();

  await expect(citationDialog).toBeVisible();

  // 10. The drawer closes with Escape.
  await page.keyboard.press("Escape");

  await expect(citationDialog).toHaveCount(0);
});

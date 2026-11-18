import { test, expect } from "@playwright/test";

/**
 * The uploader keeps its own extension list so a wrong file fails before
 * a network round-trip. That list is a second source of truth, and it has
 * already drifted once: `.xlsx` and `.csv` were added to the `<input accept>`
 * and to the server, but the JavaScript gate still refused them, so a
 * perfectly valid spreadsheet never left the browser.
 *
 * These tests pin the client gate to the formats the API accepts.
 */

const XLSX_MIME =
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

/**
 * A placeholder payload, not a spreadsheet. The POST is mocked, so these
 * bytes never reach a parser — what the test exercises is the gate that
 * decides whether the file leaves the browser at all.
 */
function xlsxBuffer(): Buffer {
  return Buffer.from("PK\u0003\u0004placeholder spreadsheet bytes", "utf8");
}

async function signIn(page: import("@playwright/test").Page) {
  await page.route(/\/auth\/login\/?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        access: "eyJhbGciOiJub25lIn0.eyJleHAiOjQwMDAwMDAwMDB9.signature",
        refresh: "e2e-refresh-token",
      }),
    }),
  );

  await page.route(/\/auth\/me\/?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: 2,
        username: "e2e-member",
        role: "Member",
        department_id: 1,
        department_name: "IT",
      }),
    }),
  );

  await page.route(/\/departments\/?$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{ id: 1, name: "IT" }]),
    }),
  );

  await page.route(/\/departments\/readiness\/?$/, (route) =>
    route.fulfill({
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
    }),
  );

  await page.goto("/login");
  await page.getByLabel("Username").fill("e2e-member");
  await page.getByLabel("Password").fill("E2E-test-password");
  await page.getByRole("button", { name: "Login" }).click();

  await expect(page).toHaveURL(/\/$/, { timeout: 15000 });
}

test("an xlsx file passes the client-side gate and reaches the API", async ({
  page,
}) => {
  let uploadBody = "";

  await page.route(/\/documents\/?$/, async (route) => {
    if (route.request().method() === "POST") {
      const body = await route.request().postDataBuffer();
      uploadBody = body?.toString("utf8") ?? "";

      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: 201,
          title: "Price list",
          file_name: "prices.xlsx",
          filename: "prices.xlsx",
          department: 1,
          department_name: "IT",
          status: "Pending",
          file_size: 4096,
        }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  await signIn(page);

  await page.getByLabel("Choose a document file").setInputFiles({
    name: "prices.xlsx",
    mimeType: XLSX_MIME,
    buffer: xlsxBuffer(),
  });

  await page.locator("#document-title").fill("Price list");
  await page.locator("#document-department").selectOption("1");
  await page.getByRole("button", { name: "Upload Document" }).click();

  await expect(
    page.getByRole("status").getByText("Document uploaded successfully."),
  ).toBeVisible();

  // The file actually left the browser. This is the assertion that fails
  // when the extension list drifts.
  expect(uploadBody).toContain("prices.xlsx");
});

test("a csv file passes the client-side gate too", async ({ page }) => {
  let uploadBody = "";

  await page.route(/\/documents\/?$/, async (route) => {
    if (route.request().method() === "POST") {
      const body = await route.request().postDataBuffer();
      uploadBody = body?.toString("utf8") ?? "";

      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: 202,
          title: "Prices",
          file_name: "prices.csv",
          filename: "prices.csv",
          department: 1,
          department_name: "IT",
          status: "Pending",
          file_size: 64,
        }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  await signIn(page);

  await page.getByLabel("Choose a document file").setInputFiles({
    name: "prices.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("Product,Price\nWidget A,120\n", "utf8"),
  });

  await page.locator("#document-title").fill("Prices");
  await page.locator("#document-department").selectOption("1");
  await page.getByRole("button", { name: "Upload Document" }).click();

  await expect(
    page.getByRole("status").getByText("Document uploaded successfully."),
  ).toBeVisible();

  expect(uploadBody).toContain("prices.csv");
});

test("an image is still refused, and the message names the real formats", async ({
  page,
}) => {
  let posted = false;

  await page.route(/\/documents\/?$/, async (route) => {
    if (route.request().method() === "POST") {
      posted = true;
    }

    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([]),
    });
  });

  await signIn(page);

  await page.getByLabel("Choose a document file").setInputFiles({
    name: "diagram.png",
    mimeType: "image/png",
    buffer: Buffer.from("89504e470d0a1a0a", "hex"),
  });

  await page.locator("#document-title").fill("Diagram");
  await page.locator("#document-department").selectOption("1");
  await page.getByRole("button", { name: "Upload Document" }).click();

  await expect(
    page.getByRole("alert").filter({ hasText: "XLSX" }),
  ).toBeVisible();

  // Refused locally: nothing was sent.
  expect(posted).toBeFalsy();
});

import { expect, test, type Page } from "@playwright/test";

/**
 * Document versioning, from the workspace page.
 *
 * The backend is mocked here because the behaviour under test is the
 * wiring: the row offers "New version", the chosen file goes to
 * `/documents/{id}/versions/`, and the list then shows the replacement
 * with its version badge. The archiving rules themselves are covered
 * by the Django tests.
 */

const FAKE_TOKEN = "eyJhbGciOiJub25lIn0.eyJleHAiOjQwMDAwMDAwMDB9.signature";

type Row = {
	id: number;
	title: string;
	department: number;
	status: string;
	created_at: string;
	is_system: boolean;
	version: number;
	parent_document: number | null;
};

const firstVersion: Row = {
	id: 1,
	title: "Travel policy",
	department: 1,
	status: "Indexed",
	created_at: "2026-11-01T09:00:00Z",
	is_system: false,
	version: 1,
	parent_document: null,
};

const secondVersion: Row = {
	...firstVersion,
	id: 2,
	status: "Pending",
	created_at: "2026-11-16T09:00:00Z",
	version: 2,
	parent_document: 1,
};

async function signIn(page: Page) {
	await page.addInitScript(
		([access, refresh]) => {
			localStorage.setItem("access_token", access);
			localStorage.setItem("refresh_token", refresh);
		},
		[FAKE_TOKEN, "e2e-refresh-token"],
	);
}

async function mockWorkspace(
	page: Page,
	options: {
		documents: () => Row[];
		onVersionUpload?: (url: URL) => void;
	} = { documents: () => [firstVersion] },
) {
	await page.route(/\/auth\/me\/?/, async (route) => {
		await route.fulfill({
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
		});
	});

	await page.route(/\/departments\/readiness\//, async (route) => {
		await route.fulfill({
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
		});
	});

	await page.route(/\/departments\/$/, async (route) => {
		await route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify([{ id: 1, name: "IT" }]),
		});
	});

	await page.route(/\/documents\/\d+\/versions\//, async (route) => {
		options.onVersionUpload?.(new URL(route.request().url()));

		await route.fulfill({
			status: 201,
			contentType: "application/json",
			body: JSON.stringify({
				document_id: 2,
				version: 2,
				parent_document_id: 1,
				archived_document_id: 1,
				status: "Pending",
			}),
		});
	});

	await page.route(/\/documents\/$/, async (route) => {
		if (route.request().method() === "GET") {
			await route.fulfill({
				status: 200,
				contentType: "application/json",
				body: JSON.stringify(options.documents()),
			});

			return;
		}

		await route.fulfill({ status: 201, body: "{}" });
	});
}

test("a first upload shows no version badge", async ({ page }) => {
	await signIn(page);
	await mockWorkspace(page);

	await page.goto("/");

	await expect(page.getByText("Travel policy")).toBeVisible();
	await expect(page.getByTestId("document-version-badge")).toHaveCount(0);
});

test("uploading a replacement posts to the versions endpoint", async ({
	page,
}) => {
	let uploaded = false;
	const calls: string[] = [];

	await signIn(page);
	await mockWorkspace(page, {
		documents: () => (uploaded ? [secondVersion] : [firstVersion]),
		onVersionUpload: (url) => {
			calls.push(url.pathname);
			uploaded = true;
		},
	});

	await page.goto("/");

	const row = page.getByRole("row", { name: /Travel policy/ });

	const chooserPromise = page.waitForEvent("filechooser");

	await row.getByTestId("document-new-version").click();

	const chooser = await chooserPromise;

	await chooser.setFiles({
		name: "travel-policy-v2.txt",
		mimeType: "text/plain",
		buffer: Buffer.from("Receipts must be submitted within 14 days."),
	});

	await expect
		.poll(() => calls[calls.length - 1])
		.toBe("/api/documents/1/versions/");

	// The list is refetched, so the row now carries the new version.
	await expect(page.getByTestId("document-version-badge")).toHaveText("v2");
	await expect(
		page.getByText("Version 2 uploaded. The previous version was archived."),
	).toBeVisible();
});

test("a platform-generated document offers no version action", async ({
	page,
}) => {
	await signIn(page);
	await mockWorkspace(page, {
		documents: () => [
			{ ...firstVersion, id: 9, title: "System guide", is_system: true },
		],
	});

	await page.goto("/");

	const row = page.getByRole("row", { name: /System guide/ });

	await expect(row.getByTestId("document-new-version")).toHaveCount(0);
	await expect(row).toContainText("Managed by the platform");
});

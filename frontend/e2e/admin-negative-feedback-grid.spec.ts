import { expect, test, type Page } from "@playwright/test";

/**
 * Sub-task 3 — the data grid of answers that got a thumbs-down.
 *
 * What is being verified is the workflow the acceptance criteria
 * describe: an admin opens the list, reads the user's comment, expands
 * the answer that produced it, narrows the list by department or free
 * text, and pages through the rest.
 */

const FAKE_TOKEN = "eyJhbGciOiJub25lIn0.eyJleHAiOjQwMDAwMDAwMDB9.signature";

const analyticsPayload = {
	total_documents: 12,
	total_file_size_bytes: 1024,
	total_searches: 40,
	departments: [
		{
			department_id: 1,
			department_name: "IT",
			document_count: 8,
			file_size_bytes: 1024,
			search_count: 30,
		},
		{
			department_id: 2,
			department_name: "Finance",
			document_count: 4,
			file_size_bytes: 512,
			search_count: 10,
		},
	],
	recent_searches: [],
};

const metricsPayload = {
	window: {
		days: 30,
		date_from: "2026-10-15",
		date_to: "2026-11-13",
		granularity: "day",
	},
	totals: {
		answers: 160,
		rated: 40,
		positive: 29,
		negative: 11,
		satisfaction_rate: 72.5,
		response_rate: 25,
		positive_share_of_answers: 18.1,
		negative_with_comment: 4,
	},
	trend: [],
	by_department: [],
};

type Row = {
	id: number;
	answer_id: string;
	question: string;
	answer_text: string;
	user_comment: string;
	username: string;
	department_id: number | null;
	department_name: string | null;
	citation_count: number;
	created_at: string;
};

const rows: Row[] = [
	{
		id: 1,
		answer_id: "11111111-1111-4111-8111-111111111111",
		question: "What is the notice period for resignation?",
		answer_text: "The notice period is 60 days for everyone.",
		user_comment: "It is 30 days for employees, not 60.",
		username: "sara",
		department_id: 1,
		department_name: "IT",
		citation_count: 2,
		created_at: "2026-11-12T09:30:00Z",
	},
	{
		id: 2,
		answer_id: "22222222-2222-4222-8222-222222222222",
		question: "How do I claim a reimbursement?",
		answer_text: "Send the receipt to the HR inbox.",
		user_comment: "",
		username: "omid",
		department_id: 2,
		department_name: "Finance",
		citation_count: 0,
		created_at: "2026-11-11T15:00:00Z",
	},
];

async function signInAsAdmin(page: Page) {
	await page.addInitScript(
		([access, refresh]) => {
			localStorage.setItem("access_token", access);
			localStorage.setItem("refresh_token", refresh);
		},
		[FAKE_TOKEN, "e2e-refresh-token"],
	);
}

async function mockAdminSurface(
	page: Page,
	options: { onGridRequest?: (url: URL) => void } = {},
) {
	await page.route(/\/auth\/me\/?/, async (route) => {
		await route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify({
				id: 1,
				username: "e2e-admin",
				role: "Admin",
				department_id: 1,
				department_name: "IT",
				tenant_id: 1,
				tenant_name: "E2E Org",
			}),
		});
	});

	await page.route(/\/admin\/analytics\//, async (route) => {
		await route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify(analyticsPayload),
		});
	});

	await page.route(/\/admin\/quality-metrics\//, async (route) => {
		await route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify(metricsPayload),
		});
	});

	await page.route(/\/admin\/quality-feedback\//, async (route) => {
		const url = new URL(route.request().url());
		options.onGridRequest?.(url);

		const pageNumber = Number(url.searchParams.get("page") ?? "1");
		const search = url.searchParams.get("search") ?? "";

		// A tiny stand-in for the paginated endpoint: page 1 carries both
		// rows and a `next`, page 2 carries a third one.
		const payload =
			pageNumber === 1
				? {
						count: 3,
						next: "http://127.0.0.1:8000/api/admin/quality-feedback/?page=2",
						previous: null,
						results: search
							? rows.filter((row) => row.user_comment.includes(search))
							: rows,
					}
				: {
						count: 3,
						next: null,
						previous:
							"http://127.0.0.1:8000/api/admin/quality-feedback/?page=1",
						results: [
							{
								...rows[0],
								id: 3,
								question: "When is the payroll run?",
								answer_text: "Every 25th.",
								user_comment: "Wrong, it moved to the 28th.",
								username: "neda",
							},
						],
					};

		await route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify(payload),
		});
	});
}

test("the grid lists the thumbs-down rows with their comments", async ({
	page,
}) => {
	await signInAsAdmin(page);
	await mockAdminSurface(page);

	await page.goto("/admin");

	const grid = page.getByTestId("negative-feedback-grid");
	await expect(grid).toBeVisible();

	await expect(page.getByTestId("negative-feedback-row")).toHaveCount(2);
	await expect(grid).toContainText("It is 30 days for employees, not 60.");
	await expect(grid).toContainText("sara");
	await expect(grid).toContainText("Finance");
	await expect(page.getByTestId("negative-feedback-total")).toContainText("3");
});

test("the answer text is hidden until the admin expands it", async ({
	page,
}) => {
	await signInAsAdmin(page);
	await mockAdminSurface(page);

	await page.goto("/admin");

	const grid = page.getByTestId("negative-feedback-grid");
	const answer = "The notice period is 60 days for everyone.";

	// Collapsed `<details>` content is still in the DOM, so the check is
	// about visibility, not about text presence.
	await expect(grid.getByText(answer)).toBeHidden();

	await grid.getByText("Show the answer").first().click();

	await expect(grid.getByText(answer)).toBeVisible();
	await expect(grid.getByText("2 citations")).toBeVisible();
});

test("paging asks the API for the next page", async ({ page }) => {
	const requestedPages: string[] = [];

	await signInAsAdmin(page);
	await mockAdminSurface(page, {
		onGridRequest: (url) => {
			requestedPages.push(url.searchParams.get("page") ?? "");
		},
	});

	await page.goto("/admin");

	const grid = page.getByTestId("negative-feedback-grid");
	await expect(page.getByTestId("negative-feedback-row")).toHaveCount(2);

	// Scoped to the grid and matched exactly: `name` is a substring match
	// by default, so a page-level lookup for "Next" also hits the
	// Next.js dev-tools button ("Open Next.js Dev Tools") and trips
	// strict mode.
	await grid.getByRole("button", { name: "Next", exact: true }).click();

	await expect
		.poll(() => requestedPages[requestedPages.length - 1])
		.toBe("2");
	await expect(
		page.getByTestId("negative-feedback-grid"),
	).toContainText("Wrong, it moved to the 28th.");
});

test("typing in the search box sends a debounced search query", async ({
	page,
}) => {
	const searches: string[] = [];

	await signInAsAdmin(page);
	await mockAdminSurface(page, {
		onGridRequest: (url) => {
			const search = url.searchParams.get("search");

			if (search !== null) {
				searches.push(search);
			}
		},
	});

	await page.goto("/admin");
	await expect(page.getByTestId("negative-feedback-row")).toHaveCount(2);

	await page
		.getByPlaceholder("Search the question, the answer or the comment")
		.fill("notice");

	await expect.poll(() => searches[searches.length - 1]).toBe("notice");
});

test("an empty result explains itself instead of showing an empty table", async ({
	page,
}) => {
	await signInAsAdmin(page);

	await page.route(/\/auth\/me\/?/, async (route) => {
		await route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify({
				id: 1,
				username: "e2e-admin",
				role: "Admin",
				department_id: 1,
				department_name: "IT",
				tenant_id: 1,
				tenant_name: "E2E Org",
			}),
		});
	});

	await page.route(/\/admin\/analytics\//, async (route) => {
		await route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify(analyticsPayload),
		});
	});

	await page.route(/\/admin\/quality-metrics\//, async (route) => {
		await route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify(metricsPayload),
		});
	});

	await page.route(/\/admin\/quality-feedback\//, async (route) => {
		await route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify({
				count: 0,
				next: null,
				previous: null,
				results: [],
			}),
		});
	});

	await page.goto("/admin");

	await expect(page.getByTestId("negative-feedback-empty")).toBeVisible();
	await expect(page.getByTestId("negative-feedback-row")).toHaveCount(0);
});

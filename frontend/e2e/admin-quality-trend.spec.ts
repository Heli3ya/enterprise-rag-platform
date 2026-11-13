import { expect, test, type Page } from "@playwright/test";

/**
 * Sub-task 2 — the "answer quality over time" chart in the admin panel.
 *
 * The backend is mocked: these tests are about what the panel does with
 * the numbers, not about how the numbers were computed (that is
 * tests/test_quality_metrics_api.py). What matters here is that a null
 * rate is rendered as "no data" rather than 0%, that switching the
 * window actually asks the API for that window, and that a failure
 * leaves a retry path instead of an empty box.
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
	],
	recent_searches: [],
};

function trendPoint(date: string, rated: number, positive: number) {
	return {
		date,
		rated,
		positive,
		negative: rated - positive,
		satisfaction_rate: rated === 0 ? null : (positive / rated) * 100,
	};
}

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
	trend: [
		trendPoint("2026-10-15", 4, 3),
		trendPoint("2026-10-16", 0, 0),
		trendPoint("2026-10-17", 6, 5),
		trendPoint("2026-10-18", 8, 6),
	],
	by_department: [
		{
			department_id: 1,
			department_name: "IT",
			rated: 5,
			positive: 2,
			negative: 3,
			satisfaction_rate: 40,
		},
		{
			department_id: 2,
			department_name: "HR",
			rated: 2,
			positive: 2,
			negative: 0,
			satisfaction_rate: 100,
		},
		{
			department_id: 3,
			department_name: "Knowledge Base",
			rated: 0,
			positive: 0,
			negative: 0,
			satisfaction_rate: null,
		},
	],
};

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
	options: { metrics?: unknown; onMetricsRequest?: (url: URL) => void } = {},
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

	// No `$` anchor: the URL carries `?days=30`, so an anchored pattern
	// would silently miss and the request would hit the real backend.
	await page.route(/\/admin\/quality-metrics\//, async (route) => {
		options.onMetricsRequest?.(new URL(route.request().url()));

		await route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify(options.metrics ?? metricsPayload),
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
}

test("the panel shows the satisfaction rate and the counts behind it", async ({
	page,
}) => {
	await signInAsAdmin(page);
	await mockAdminSurface(page);

	await page.goto("/admin");

	const trend = page.getByTestId("quality-trend");
	await expect(trend).toBeVisible();

	await expect(page.getByTestId("quality-satisfaction-rate")).toHaveText(
		"72.5%",
	);
	await expect(page.getByTestId("quality-rated-count")).toHaveText("40");
	await expect(page.getByTestId("quality-negative-count")).toHaveText("11");
	await expect(page.getByTestId("quality-response-rate")).toHaveText("25.0%");

	// The number alone is not enough: 29 of 40 must be visible.
	await expect(trend).toContainText("29");

	// The brief's literal metric — positive ÷ all answers — is the
	// secondary line, not the headline.
	await expect(page.getByTestId("quality-positive-share")).toHaveText(
		"18.1% of all delivered answers",
	);
});

test("a null rate is shown as no data, never as zero percent", async ({
	page,
}) => {
	await signInAsAdmin(page);
	await mockAdminSurface(page, {
		metrics: {
			...metricsPayload,
			totals: {
				answers: 12,
				rated: 0,
				positive: 0,
				negative: 0,
				satisfaction_rate: null,
				response_rate: null,
				positive_share_of_answers: null,
				negative_with_comment: 0,
			},
			trend: [trendPoint("2026-10-15", 0, 0)],
			by_department: [],
		},
	});

	await page.goto("/admin");

	await expect(page.getByTestId("quality-satisfaction-rate")).toHaveText("—");
	await expect(page.getByTestId("quality-trend-empty")).toBeVisible();
});

test("the breakdown names the worst department first and the unrated last", async ({
	page,
}) => {
	await signInAsAdmin(page);
	await mockAdminSurface(page);

	await page.goto("/admin");

	const rows = page.getByTestId("quality-department-row");
	await expect(rows).toHaveCount(3);

	// 40% before 100%, even though HR sorts first alphabetically: the
	// list is a work queue, not a directory.
	await expect(rows.nth(0)).toContainText("IT");
	await expect(rows.nth(0)).toContainText("40.0%");
	await expect(rows.nth(0)).toContainText("3 negative");
	await expect(rows.nth(1)).toContainText("HR");

	// No ratings is "—", never 0%: a department nobody rated is not a
	// department that failed.
	await expect(rows.nth(2)).toContainText("Knowledge Base");
	await expect(rows.nth(2)).toContainText("—");
});

test("switching the window refetches with the requested number of days", async ({
	page,
}) => {
	const requestedDays: string[] = [];

	await signInAsAdmin(page);
	await mockAdminSurface(page, {
		onMetricsRequest: (url) => {
			requestedDays.push(url.searchParams.get("days") ?? "");
		},
	});

	await page.goto("/admin");
	await expect(page.getByTestId("quality-trend")).toBeVisible();
	await expect(page.getByTestId("quality-satisfaction-rate")).toHaveText(
		"72.5%",
	);

	await page.getByRole("button", { name: "7 days" }).click();

	await expect
		.poll(() => requestedDays[requestedDays.length - 1])
		.toBe("7");
});

test("a failed request offers a retry that refetches", async ({ page }) => {
	// A flag instead of a request counter: React re-runs effects in
	// development, so "fail the first request" is not deterministic.
	let shouldFail = true;

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

	await page.route(/\/admin\/quality-feedback\//, async (route) => {
		await route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify({ count: 0, next: null, previous: null, results: [] }),
		});
	});

	await page.route(/\/admin\/quality-metrics\//, async (route) => {
		if (shouldFail) {
			await route.fulfill({
				status: 500,
				contentType: "application/json",
				body: JSON.stringify({ error: "boom" }),
			});
			return;
		}

		await route.fulfill({
			status: 200,
			contentType: "application/json",
			body: JSON.stringify(metricsPayload),
		});
	});

	await page.goto("/admin");

	const trend = page.getByTestId("quality-trend");
	await expect(trend).toContainText(
		"Could not load the quality metrics. Please try again.",
	);

	shouldFail = false;

	await trend.getByRole("button", { name: "Retry" }).click();

	await expect(page.getByTestId("quality-satisfaction-rate")).toHaveText(
		"72.5%",
	);
});

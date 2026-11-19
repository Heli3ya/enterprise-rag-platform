import { test, expect, type Page } from "@playwright/test";

/**
 * How an answer is displayed.
 *
 * The model is asked for plain prose, but a small local model still
 * emits `**bold**` and `- bullets`. Before this spec existed, those
 * markers reached the screen as literal characters and the Persian
 * answer looked like broken markup. Two properties are pinned here:
 *
 * 1. Markdown markers become real elements, never visible characters.
 * 2. Persian answers get an RTL block even when the UI is in English,
 *    and the `[n]` citation chips stay isolated LTR so the bidi
 *    algorithm cannot mirror their brackets.
 */

const PERSIAN_ANSWER = [
	"**مرخصی سالانه** طبق آیین‌نامه ۲۰ روز است [93].",
	"",
	"- ثبت درخواست در سامانه منابع انسانی [94]",
	"- تأیید مدیر مستقیم [94]",
].join("\n");

const ENGLISH_ANSWER = "**Annual leave** is 20 days [93].";

const CITATIONS = [
	{
		document_id: 12,
		filename: "handbook.pdf",
		department: "IT",
		chunk_id: 93,
		chunk_index: 3,
		snippet: "Employees receive 20 days of annual leave.",
	},
	{
		document_id: 12,
		filename: "handbook.pdf",
		department: "IT",
		chunk_id: 94,
		chunk_index: 4,
		snippet: "Requests are approved by the direct manager.",
	},
];

async function mockSignedInSurface(
	page: Page,
	answer: string,
	citations = CITATIONS,
) {
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

	await page.route(/\/chat\/ask\/?$/, async (route) => {
		await route.fulfill({
			status: 200,
			headers: {
				"Content-Type": "text/event-stream",
				"Cache-Control": "no-cache",
			},
			body:
				'event: meta\ndata: {"answer_id":"e2e-answer","conversation_id":"e2e-conv"}\n\n' +
				`event: token\ndata: ${JSON.stringify({ content: answer })}\n\n` +
				`event: citations\ndata: ${JSON.stringify(citations)}\n\n` +
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

	await page
		.getByPlaceholder("Type your question...")
		.fill("مرخصی سالانه چند روز است؟");

	await page.getByRole("button", { name: "Send" }).click();
}

test("a Persian answer renders RTL with real elements, not markdown markers", async ({
	page,
}) => {
	await mockSignedInSurface(page, PERSIAN_ANSWER);
	await signInAndAsk(page);

	const answer = page.locator(".answer-content").last();
	await expect(answer).toBeVisible();

	// The UI is in English, so the RTL block comes from the answer text
	// itself — the same behaviour the Persian UI relies on.
	await expect(answer).toHaveAttribute("dir", "rtl");

	// `**bold**` became a <strong>, and no asterisk survived.
	await expect(answer.locator("strong")).toHaveText("مرخصی سالانه");
	expect(await answer.innerText()).not.toContain("**");

	// The list became a real list, without the leading dashes.
	await expect(answer.locator("li")).toHaveCount(2);
	expect(await answer.locator("li").first().innerText()).not.toContain("- ");

	// The whole sentence, including its citation, is still there.
	await expect(answer).toContainText("طبق آیین‌نامه ۲۰ روز است");
});

test("citation chips are isolated LTR inside RTL text", async ({ page }) => {
	await mockSignedInSurface(page, PERSIAN_ANSWER);
	await signInAndAsk(page);

	const chip = page
		.getByRole("button", { name: "Open citation [93]" })
		.first();

	await expect(chip).toBeVisible();
	await expect(chip).toHaveText("[93]");

	// Without isolation the brackets are mirrored by the RTL paragraph
	// and the marker reads `]93[`; the numbers themselves also jump to
	// the wrong side of the brackets.
	const style = await chip.evaluate((element) => {
		const computed = window.getComputedStyle(element);

		return {
			direction: computed.direction,
			unicodeBidi: computed.unicodeBidi,
		};
	});

	expect(style.direction).toBe("ltr");
	expect(style.unicodeBidi).toBe("isolate");
});

test("an English answer keeps its LTR direction", async ({ page }) => {
	await mockSignedInSurface(page, ENGLISH_ANSWER);
	await signInAndAsk(page);

	const answer = page.locator(".answer-content").last();

	await expect(answer).toHaveAttribute("dir", "ltr");
	await expect(answer.locator("strong")).toHaveText("Annual leave");
});

test("a citation written in Persian digits still becomes a chip", async ({
	page,
}) => {
	// The model cites `[۶۶]` in a Persian answer. `\d` in JavaScript is
	// ASCII-only, so without normalization this marker stays plain text
	// and the citation is silently unreachable.
	await mockSignedInSurface(page, "مرخصی ۲۰ روز است [۶۶].", [
		{
			document_id: 12,
			filename: "handbook.pdf",
			department: "IT",
			chunk_id: 66,
			chunk_index: 1,
			snippet: "Employees receive 20 days of annual leave.",
		},
	]);
	await signInAndAsk(page);

	const chip = page.getByRole("button", { name: "Open citation [66]" });

	await expect(chip).toBeVisible();
	await expect(chip).toHaveText("[66]");
});

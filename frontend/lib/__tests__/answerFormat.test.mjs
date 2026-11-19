/**
 * Unit tests for the answer formatter.
 *
 * These run on the plain Node test runner, without a DOM and without a
 * bundler: `npm run test:unit`. The module is pure, so this is the
 * cheapest place to pin the behaviour — the Playwright spec only has to
 * prove that the component wires these blocks to real elements.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { directionForText, parseAnswerBlocks } from "../answerFormat.ts";
import { parseAnswerSegments } from "../citations.ts";

function inlineText(runs) {
	return runs
		.map((run) => {
			if (run.type === "text") {
				return run.value;
			}

			if (run.type === "code") {
				return run.value;
			}

			return inlineText(run.children);
		})
		.join("");
}

function blockText(block) {
	return block.type === "list"
		? block.items.map((item) => inlineText(item)).join(" | ")
		: inlineText(block.runs);
}

function plainText(blocks) {
	return blocks.map(blockText).join("\n");
}

describe("parseAnswerBlocks", () => {
	it("returns no blocks for empty or whitespace-only text", () => {
		assert.deepEqual(parseAnswerBlocks(""), []);
		assert.deepEqual(parseAnswerBlocks("   \n\n  \n"), []);
	});

	it("keeps a single line as one paragraph", () => {
		const blocks = parseAnswerBlocks("مرخصی سالانه ۲۰ روز است.");

		assert.equal(blocks.length, 1);
		assert.equal(blocks[0].type, "paragraph");
		assert.equal(plainText(blocks), "مرخصی سالانه ۲۰ روز است.");
	});

	it("splits paragraphs on a blank line", () => {
		const blocks = parseAnswerBlocks("خط اول.\n\nخط دوم.");

		assert.equal(blocks.length, 2);
		assert.equal(plainText(blocks), "خط اول.\nخط دوم.");
	});

	it("joins soft-wrapped lines instead of keeping a broken column", () => {
		const blocks = parseAnswerBlocks("این جمله\nادامه دارد.");

		assert.equal(blocks.length, 1);
		assert.equal(plainText(blocks), "این جمله ادامه دارد.");
	});

	it("turns **bold** into a strong run", () => {
		const blocks = parseAnswerBlocks("**مرخصی سالانه** ۲۰ روز است.");

		assert.equal(blocks[0].runs[0].type, "strong");
		assert.equal(blocks[0].runs[0].children[0].value, "مرخصی سالانه");
		assert.equal(plainText(blocks), "مرخصی سالانه ۲۰ روز است.");
	});

	it("supports __bold__ as well", () => {
		const blocks = parseAnswerBlocks("__مهم__ است.");

		assert.equal(blocks[0].runs[0].type, "strong");
	});

	it("leaves an unclosed marker as literal text while streaming", () => {
		const blocks = parseAnswerBlocks("**مرخصی");

		assert.equal(blocks[0].runs.length, 1);
		assert.equal(blocks[0].runs[0].type, "text");
		assert.equal(blocks[0].runs[0].value, "**مرخصی");
	});

	it("turns `code` into a code run and keeps the inner text", () => {
		const blocks = parseAnswerBlocks("کد `ORBIT-742` را وارد کنید.");

		assert.deepEqual(
			blocks[0].runs.map((run) => run.type),
			["text", "code", "text"],
		);
		assert.equal(blocks[0].runs[1].value, "ORBIT-742");
	});

	it("parses a code span nested inside bold", () => {
		const blocks = parseAnswerBlocks("**کد `A-1`** معتبر است.");

		assert.equal(blocks[0].runs[0].type, "strong");
		assert.deepEqual(
			blocks[0].runs[0].children.map((run) => run.type),
			["text", "code"],
		);
		assert.equal(plainText(blocks), "کد A-1 معتبر است.");
	});

	it("parses dash, star and bullet markers as one unordered list", () => {
		const blocks = parseAnswerBlocks("- اول\n* دوم\n• سوم");

		assert.equal(blocks.length, 1);
		assert.equal(blocks[0].type, "list");
		assert.equal(blocks[0].ordered, false);
		assert.deepEqual(
			blocks[0].items.map((item) => inlineText(item)),
			["اول", "دوم", "سوم"],
		);
	});

	it("parses numbered items as an ordered list", () => {
		const blocks = parseAnswerBlocks("1. اول\n2) دوم");

		assert.equal(blocks[0].type, "list");
		assert.equal(blocks[0].ordered, true);
		assert.equal(blocks[0].items.length, 2);
	});

	it("keeps one list across a blank line between items", () => {
		const blocks = parseAnswerBlocks("- اول\n\n- دوم");

		assert.equal(blocks.length, 1);
		assert.equal(blocks[0].items.length, 2);
	});

	it("appends a wrapped line to the item above it", () => {
		const blocks = parseAnswerBlocks("- خط اول\n  ادامه دارد");

		assert.equal(blocks[0].items.length, 1);
		assert.equal(inlineText(blocks[0].items[0]), "خط اول ادامه دارد");
	});

	it("ends a list when a paragraph follows it", () => {
		const blocks = parseAnswerBlocks("- اول\n- دوم\n\nجمع‌بندی.");

		assert.equal(blocks[0].type, "list");
		assert.equal(blocks[1].type, "paragraph");
	});

	it("renders a heading as a bold paragraph without the hashes", () => {
		const blocks = parseAnswerBlocks("## نتیجه");

		assert.equal(blocks[0].type, "paragraph");
		assert.equal(blocks[0].runs[0].type, "strong");
		assert.equal(plainText(blocks), "نتیجه");
	});

	it("drops horizontal rules and fences but keeps their content", () => {
		const blocks = parseAnswerBlocks("---\n```\nخط دستور\n```\n***");

		assert.equal(blocks.length, 1);
		assert.equal(plainText(blocks), "خط دستور");
	});

	it("flattens a table row and drops the separator row", () => {
		const blocks = parseAnswerBlocks(
			"| کالا | قیمت |\n|---|---|\n| بلبرینگ | ۴۵ |",
		);

		assert.equal(blocks.length, 2);
		assert.equal(plainText(blocks), "کالا · قیمت\nبلبرینگ · ۴۵");
	});

	it("keeps citation markers inside the text for the citation layer", () => {
		const blocks = parseAnswerBlocks("مرخصی ۲۰ روز است [93].");

		assert.equal(plainText(blocks), "مرخصی ۲۰ روز است [93].");
	});

	it("never interprets HTML, so a script tag stays literal text", () => {
		const blocks = parseAnswerBlocks("<script>alert(1)</script>");

		assert.equal(blocks[0].runs[0].type, "text");
		assert.equal(blocks[0].runs[0].value, "<script>alert(1)</script>");
	});

	it("strips quote markers", () => {
		const blocks = parseAnswerBlocks("> نقل قول");

		assert.equal(plainText(blocks), "نقل قول");
	});
});

describe("directionForText", () => {
	it("detects Persian as RTL", () => {
		assert.equal(directionForText("مرخصی سالانه ۲۰ روز است."), "rtl");
	});

	it("detects English as LTR", () => {
		assert.equal(directionForText("Employees get 20 days."), "ltr");
	});

	it("follows the dominant script, not the first character", () => {
		assert.equal(directionForText("SLA یعنی توافق سطح سرویس است."), "rtl");
		assert.equal(directionForText("The word مرخصی means leave."), "ltr");
	});

	it("treats Persian digits as RTL content", () => {
		assert.equal(directionForText("۱۲۳"), "rtl");
	});

	it("defaults to LTR when there is no strong character", () => {
		assert.equal(directionForText(""), "ltr");
		assert.equal(directionForText("123 456"), "ltr");
	});
});

describe("parseAnswerSegments", () => {
	it("splits text around an ASCII citation marker", () => {
		const segments = parseAnswerSegments("Leave is 20 days [93].");

		assert.deepEqual(
			segments.map((segment) => segment.type),
			["text", "citation", "text"],
		);
		assert.equal(segments[1].chunkId, 93);
		assert.equal(segments[1].raw, "[93]");
	});

	it("normalizes Persian digits in the marker to the chunk id", () => {
		// The model cites `[۶۶]` in a Persian answer; the id is an
		// integer and the source card shows "Chunk 66".
		const segments = parseAnswerSegments("مرخصی ۲۰ روز است [۶۶].");

		assert.equal(segments[1].type, "citation");
		assert.equal(segments[1].chunkId, 66);
		assert.equal(segments[1].raw, "[66]");
	});

	it("normalizes Arabic-Indic digits too", () => {
		const segments = parseAnswerSegments("نتیجه [٩٣] است.");

		assert.equal(segments[1].chunkId, 93);
	});

	it("keeps the text around a marker intact and in order", () => {
		const segments = parseAnswerSegments("الف [1] ب [2] ج");

		assert.equal(
			segments
				.filter((segment) => segment.type === "text")
				.map((segment) => segment.value)
				.join(""),
			"الف  ب  ج",
		);
	});

	it("ignores brackets that do not hold a number", () => {
		const segments = parseAnswerSegments("مقدار [نامشخص] است.");

		assert.equal(
			segments.filter((segment) => segment.type === "citation").length,
			0,
		);
	});
});

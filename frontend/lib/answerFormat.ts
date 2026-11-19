/**
 * Formatting for assistant answers.
 *
 * The prompt asks the model to answer in plain prose, but a small local
 * model still slips into Markdown: `**bold**`, `- bullets`, `# headings`,
 * `| tables |`, fenced code. Rendering that as raw text is what showed
 * asterisks and pipes literally in the answer bubble.
 *
 * A full Markdown parser would fix the display and add two problems: a
 * dependency to keep patched, and an HTML sink in the one place where
 * untrusted model output is displayed. So this module understands only
 * the constructs that actually appear in answers, returns plain data,
 * and `AnswerContent` maps that data to React elements. No HTML string is
 * ever produced, so `<script>` in an answer stays the five characters it
 * looks like.
 *
 * Everything here is pure and synchronous: it runs on every streamed
 * token, so it must stay cheap and never throw.
 */

export type InlineRun =
	| { type: "text"; value: string }
	| { type: "strong"; children: InlineRun[] }
	| { type: "code"; value: string };

export type AnswerBlock =
	| { type: "paragraph"; runs: InlineRun[] }
	| { type: "list"; ordered: boolean; items: InlineRun[][] };

const BULLET_PATTERN = /^ {0,3}[-*+•]\s+(.*)$/;
const ORDERED_PATTERN = /^ {0,3}\d{1,3}[.)]\s+(.*)$/;
const HEADING_PATTERN = /^ {0,3}#{1,6}\s+(.*)$/;
const RULE_PATTERN = /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/;
const FENCE_PATTERN = /^ {0,3}(?:```|~~~)/;
const TABLE_ROW_PATTERN = /^\s*\|(.+)\|\s*$/;
const QUOTE_PATTERN = /^ {0,3}>\s?/;

// One pass, left to right, so nesting works: inside `**a `b` c**` the
// bold match starts first and its content is parsed again.
const INLINE_PATTERN = /`([^`\n]+)`|\*\*(.+?)\*\*|__(.+?)__/g;

/**
 * Turn an answer into blocks the component can render.
 *
 * Soft-wrapped lines are joined with a space (Markdown semantics), which
 * is what makes a long answer stop looking like a broken column of
 * half-sentences. Fences, horizontal rules and table separators are
 * dropped as decoration; their content is kept.
 */
export function parseAnswerBlocks(text: string): AnswerBlock[] {
	const lines = normalizeNewlines(text).split("\n");
	const blocks: AnswerBlock[] = [];
	let index = 0;

	while (index < lines.length) {
		const line = lines[index];

		if (!line.trim()) {
			index += 1;
			continue;
		}

		// A fence is a formatting hint, not content: drop the delimiter
		// and keep the code as ordinary lines so nothing is lost.
		if (FENCE_PATTERN.test(line)) {
			index += 1;
			continue;
		}

		if (RULE_PATTERN.test(line)) {
			index += 1;
			continue;
		}

		if (TABLE_ROW_PATTERN.test(line)) {
			const row = TABLE_ROW_PATTERN.exec(line)?.[1] ?? "";

			// The `|---|---|` separator carries no content.
			if (!isTableDivider(row)) {
				blocks.push({
					type: "paragraph",
					runs: parseInline(flattenTableRow(row)),
				});
			}

			index += 1;
			continue;
		}

		if (BULLET_PATTERN.test(line) || ORDERED_PATTERN.test(line)) {
			const ordered = !BULLET_PATTERN.test(line);
			const items: InlineRun[][] = [];

			while (index < lines.length) {
				const itemLine = lines[index];

				if (!itemLine.trim()) {
					// A blank line ends the list unless another item of
					// the same kind follows: models often space items out.
					const next = nextNonBlank(lines, index + 1);

					if (next === -1 || !matchesListKind(lines[next], ordered)) {
						break;
					}

					index = next;
					continue;
				}

				if (BULLET_PATTERN.test(itemLine) || ORDERED_PATTERN.test(itemLine)) {
					if (!matchesListKind(itemLine, ordered)) {
						break;
					}

					const content =
						(ordered ? ORDERED_PATTERN : BULLET_PATTERN).exec(itemLine)?.[1] ??
						"";

					items.push(parseInline(content.trim()));
					index += 1;
					continue;
				}

				// A wrapped continuation of the item above it.
				const last = items[items.length - 1];

				if (!last) {
					break;
				}

				items[items.length - 1] = [
					...last,
					{ type: "text", value: " " },
					...parseInline(stripQuote(itemLine).trim()),
				];
				index += 1;
			}

			if (items.length > 0) {
				blocks.push({ type: "list", ordered, items });
			}

			continue;
		}

		const heading = HEADING_PATTERN.exec(line);

		if (heading) {
			// A heading inside a chat bubble is noise; its text is not.
			blocks.push({
				type: "paragraph",
				runs: [
					{
						type: "strong",
						children: parseInline(heading[1].trim()),
					},
				],
			});
			index += 1;
			continue;
		}

		const parts: string[] = [];

		while (index < lines.length) {
			const paragraphLine = lines[index];

			if (!paragraphLine.trim() || startsBlock(paragraphLine)) {
				break;
			}

			parts.push(stripQuote(paragraphLine).trim());
			index += 1;
		}

		if (parts.length === 0) {
			// Defensive: never leave the loop without advancing.
			index += 1;
			continue;
		}

		blocks.push({
			type: "paragraph",
			runs: parseInline(parts.join(" ")),
		});
	}

	return blocks;
}

/**
 * Direction of a piece of text, used as the `dir` of the answer block.
 *
 * `dir="auto"` looks at the first strong character only, so a Persian
 * sentence that opens with a Latin acronym ("SLA یعنی…") would be laid
 * out left-to-right. Counting strong characters instead follows the
 * dominant script, which is what a Persian-first product needs.
 */
export function directionForText(text: string): "rtl" | "ltr" {
	let rtl = 0;
	let ltr = 0;

	for (const character of text) {
		const code = character.codePointAt(0) ?? 0;

		if (isRtlCharacter(code)) {
			rtl += 1;
		} else if (isLatinCharacter(code)) {
			ltr += 1;
		}
	}

	return rtl > 0 && rtl > ltr ? "rtl" : "ltr";
}

function isRtlCharacter(code: number): boolean {
	return (
		(code >= 0x0590 && code <= 0x05ff) || // Hebrew
		(code >= 0x0600 && code <= 0x06ff) || // Arabic, Persian
		(code >= 0x0750 && code <= 0x077f) || // Arabic supplement
		(code >= 0x08a0 && code <= 0x08ff) || // Arabic extended-A
		(code >= 0xfb1d && code <= 0xfb4f) || // Hebrew presentation
		(code >= 0xfb50 && code <= 0xfdff) || // Arabic presentation A
		(code >= 0xfe70 && code <= 0xfeff) // Arabic presentation B
	);
}

function isLatinCharacter(code: number): boolean {
	return (
		(code >= 0x0041 && code <= 0x005a) ||
		(code >= 0x0061 && code <= 0x007a) ||
		(code >= 0x00c0 && code <= 0x024f)
	);
}

function parseInline(text: string): InlineRun[] {
	const runs: InlineRun[] = [];
	let lastIndex = 0;

	for (const match of text.matchAll(INLINE_PATTERN)) {
		const matchIndex = match.index ?? 0;

		if (matchIndex > lastIndex) {
			runs.push({ type: "text", value: text.slice(lastIndex, matchIndex) });
		}

		if (match[1] !== undefined) {
			runs.push({ type: "code", value: match[1] });
		} else {
			// An unclosed `**` never matches, so it stays literal text
			// until the closing pair streams in. That is the only
			// behaviour that looks sane mid-stream.
			runs.push({
				type: "strong",
				children: parseInline(match[2] ?? match[3] ?? ""),
			});
		}

		lastIndex = matchIndex + match[0].length;
	}

	if (lastIndex < text.length) {
		runs.push({ type: "text", value: text.slice(lastIndex) });
	}

	if (runs.length === 0) {
		runs.push({ type: "text", value: text });
	}

	return runs;
}

function startsBlock(line: string): boolean {
	return (
		FENCE_PATTERN.test(line) ||
		RULE_PATTERN.test(line) ||
		TABLE_ROW_PATTERN.test(line) ||
		BULLET_PATTERN.test(line) ||
		ORDERED_PATTERN.test(line) ||
		HEADING_PATTERN.test(line)
	);
}

function matchesListKind(line: string, ordered: boolean): boolean {
	return ordered ? ORDERED_PATTERN.test(line) : BULLET_PATTERN.test(line);
}

function nextNonBlank(lines: string[], from: number): number {
	for (let index = from; index < lines.length; index += 1) {
		if (lines[index].trim()) {
			return index;
		}
	}

	return -1;
}

function isTableDivider(row: string): boolean {
	return row.includes("-") && /^[\s:|-]+$/.test(row);
}

/**
 * `| a | b |` → `a · b`.
 *
 * A pipe table cannot be laid out inside a chat bubble without a real
 * table component, and left as-is it renders as a row of pipes in the
 * middle of a Persian sentence.
 */
function flattenTableRow(row: string): string {
	return row
		.split("|")
		.map((cell) => cell.trim())
		.filter((cell) => cell.length > 0)
		.join(" · ");
}

function stripQuote(line: string): string {
	return line.replace(QUOTE_PATTERN, "");
}

function normalizeNewlines(text: string): string {
	return text.replace(/\r\n?/g, "\n");
}

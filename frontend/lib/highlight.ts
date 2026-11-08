/**
 * Helpers for rendering the highlighted part of a cited chunk.
 *
 * The backend returns `[start, end)` offsets computed with the same
 * tokenizer it uses for search, so the frontend only has to slice the
 * string — no term matching in the browser.
 */

export type Range = [start: number, end: number];

/**
 * Drop anything that is not a usable range: wrong shape, out of bounds,
 * reversed, or overlapping. A malformed payload must never break the
 * rendering of the passage.
 */
export function sanitizeRanges(
	ranges: number[][] | undefined,
	length: number,
): Range[] {
	if (!Array.isArray(ranges) || length <= 0) {
		return [];
	}

	const cleaned: Range[] = [];

	for (const range of ranges) {
		if (!Array.isArray(range) || range.length < 2) {
			continue;
		}

		const start = Number(range[0]);
		const end = Number(range[1]);

		if (!Number.isInteger(start) || !Number.isInteger(end)) {
			continue;
		}

		if (start < 0 || end <= start || end > length) {
			continue;
		}

		cleaned.push([start, end]);
	}

	cleaned.sort((a, b) => a[0] - b[0]);

	const merged: Range[] = [];

	for (const range of cleaned) {
		const last = merged[merged.length - 1];

		if (last && range[0] <= last[1]) {
			last[1] = Math.max(last[1], range[1]);
			continue;
		}

		merged.push([range[0], range[1]]);
	}

	return merged;
}

export type TextPart =
	| { type: "text"; value: string; offset: number }
	| { type: "highlight"; value: string; offset: number };

/**
 * Split a passage into plain and highlighted parts.
 */
export function splitHighlighted(text: string, ranges: Range[]): TextPart[] {
	const parts: TextPart[] = [];
	let cursor = 0;

	for (const [start, end] of ranges) {
		if (start > cursor) {
			parts.push({
				type: "text",
				value: text.slice(cursor, start),
				offset: cursor,
			});
		}

		parts.push({
			type: "highlight",
			value: text.slice(start, end),
			offset: start,
		});

		cursor = end;
	}

	if (cursor < text.length) {
		parts.push({
			type: "text",
			value: text.slice(cursor),
			offset: cursor,
		});
	}

	return parts;
}

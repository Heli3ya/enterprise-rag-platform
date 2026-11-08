"use client";

import { sanitizeRanges, splitHighlighted } from "../lib/highlight";

type HighlightedTextProps = {
	text: string;
	ranges?: number[][];
};

/**
 * Render a passage with the matched query terms marked.
 *
 * With no (valid) ranges it degrades to plain text, so a semantic-only
 * match — where the words of the question never appear verbatim — still
 * renders correctly.
 */
export default function HighlightedText({
	text,
	ranges,
}: HighlightedTextProps) {
	const safeRanges = sanitizeRanges(ranges, text.length);

	if (safeRanges.length === 0) {
		return <>{text}</>;
	}

	return (
		<>
			{splitHighlighted(text, safeRanges).map((part) =>
				part.type === "highlight" ? (
					<mark
						key={`mark-${part.offset}`}
						className="rounded bg-yellow-200 px-0.5 font-semibold text-gray-900"
					>
						{part.value}
					</mark>
				) : (
					<span key={`text-${part.offset}`}>{part.value}</span>
				),
			)}
		</>
	);
}

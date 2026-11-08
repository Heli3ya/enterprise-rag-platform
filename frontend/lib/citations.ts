/**
 * Shared types and helpers for clickable citations.
 *
 * The RAG prompt asks the model to cite the *chunk id* in square
 * brackets, so `[93]` in an answer always refers to `chunk_id: 93`.
 * That is why the source list shows the same number instead of
 * renumbering the sources 1..N — the inline marker and the source
 * card must agree.
 */

export type Citation = {
	document_id: number;
	filename: string;
	department: string;
	chunk_id: number;
	title?: string;
	chunk_index?: number;
	snippet?: string;
	file_url?: string;
};

export type ChunkDetail = {
	chunk_id: number;
	chunk_index: number;
	content: string;
	document_id: number;
	document_title: string;
	filename: string;
	file_type: string;
	file_url: string;
	department: string;
	department_id: number;
	is_public: boolean;
	uploaded_by: string;
	created_at: string;
	/** `[start, end)` offsets of the matched terms inside `content`. */
	highlights?: number[][];
	matched_terms?: string[];
	preview_url?: string;
};

export type DocumentPreview = {
	document_id: number;
	title: string;
	filename: string;
	file_type: string;
	file_url: string;
	department: string;
	content: string;
	highlights: number[][];
	matched_terms: string[];
	truncated: boolean;
};

export type AnswerSegment =
	| { type: "text"; value: string; offset: number }
	| { type: "citation"; chunkId: number; raw: string; offset: number };

const CITATION_PATTERN = /\[(\d+)\]/g;

/**
 * Split an answer into plain text and citation markers so the UI can
 * render `[93]` as a button without touching the rest of the text.
 *
 * `offset` is the position in the original string; it is stable across
 * re-renders and doubles as a React key.
 */
export function parseAnswerSegments(content: string): AnswerSegment[] {
	const segments: AnswerSegment[] = [];
	let lastIndex = 0;

	for (const match of content.matchAll(CITATION_PATTERN)) {
		const matchIndex = match.index ?? 0;

		if (matchIndex > lastIndex) {
			segments.push({
				type: "text",
				value: content.slice(lastIndex, matchIndex),
				offset: lastIndex,
			});
		}

		segments.push({
			type: "citation",
			chunkId: Number(match[1]),
			raw: match[0],
			offset: matchIndex,
		});

		lastIndex = matchIndex + match[0].length;
	}

	if (lastIndex < content.length) {
		segments.push({
			type: "text",
			value: content.slice(lastIndex),
			offset: lastIndex,
		});
	}

	return segments;
}

/**
 * Index citations by chunk id for O(1) lookups while rendering.
 */
export function indexCitations(
	citations: Citation[] | undefined,
): Map<number, Citation> {
	const byChunkId = new Map<number, Citation>();

	for (const citation of citations ?? []) {
		byChunkId.set(citation.chunk_id, citation);
	}

	return byChunkId;
}

export function citationLabel(citation: Citation): string {
	return (
		citation.filename || citation.title || `Document ${citation.document_id}`
	);
}

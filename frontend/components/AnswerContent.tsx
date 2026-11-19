"use client";

import { useMemo } from "react";
import {
	type AnswerBlock,
	directionForText,
	type InlineRun,
	parseAnswerBlocks,
} from "../lib/answerFormat";
import {
	type Citation,
	indexCitations,
	parseAnswerSegments,
} from "../lib/citations";
import { useT } from "./PreferencesProvider";

type AnswerContentProps = {
	content: string;
	citations?: Citation[];
	onCitationClick: (citation: Citation) => void;
};

type RenderContext = {
	citationsByChunkId: Map<number, Citation>;
	onCitationClick: (citation: Citation) => void;
	openSource: (filename: string) => string;
	openCitation: (chunkId: number) => string;
};

/**
 * Render an assistant answer.
 *
 * The text is first turned into blocks and inline runs by
 * `lib/answerFormat` — a deliberately small subset of Markdown, because
 * a local model emits `**bold**` and `- bullets` even when told not to,
 * and showing the markers literally is what made the Persian answers
 * look broken. Blocks become real elements here; no HTML string is ever
 * built, so an answer cannot inject markup.
 *
 * `[n]` markers become buttons when a citation with that chunk id
 * exists, and stay plain text otherwise, so a hallucinated id is visible
 * but not clickable. Each marker is wrapped in an isolated LTR run:
 * inside a Persian sentence the neutral brackets would otherwise be
 * mirrored by the bidi algorithm and `[93]` would read as `]93[`.
 */
export default function AnswerContent({
	content,
	citations,
	onCitationClick,
}: AnswerContentProps) {
	const t = useT();
	const citationsByChunkId = indexCitations(citations);

	// Re-parsed on every streamed token; memoised so a re-render for an
	// unrelated reason (hover, feedback state) does not redo the work.
	const blocks = useMemo(() => parseAnswerBlocks(content), [content]);
	const direction = useMemo(() => directionForText(content), [content]);

	const context: RenderContext = {
		citationsByChunkId,
		onCitationClick,
		openSource: (filename) => `${t("Open source")}: ${filename}`,
		openCitation: (chunkId) => `${t("Open citation")} [${chunkId}]`,
	};

	return (
		<div
			dir={direction}
			className="answer-content text-start text-sm leading-6"
		>
			{blocks.map((block, index) => renderBlock(block, index, context))}
		</div>
	);
}

function renderBlock(
	block: AnswerBlock,
	index: number,
	context: RenderContext,
): React.ReactNode {
	const key = `block-${index}`;

	if (block.type === "list") {
		const ListTag = block.ordered ? "ol" : "ul";

		return (
			<ListTag
				key={key}
				className={`my-2 space-y-1 ${
					block.ordered ? "list-decimal" : "list-disc"
				}`}
			>
				{block.items.map((item, itemIndex) => (
					// biome-ignore lint/suspicious/noArrayIndexKey: the list is a pure projection of the answer text, so an item has no identity beyond its position and nothing is reordered.
					<li key={`${key}-item-${itemIndex}`}>
						{renderRuns(item, context, `${key}-item-${itemIndex}`)}
					</li>
				))}
			</ListTag>
		);
	}

	return (
		<p key={key} className="my-2 first:mt-0 last:mb-0">
			{renderRuns(block.runs, context, key)}
		</p>
	);
}

function renderRuns(
	runs: InlineRun[],
	context: RenderContext,
	keyPrefix: string,
): React.ReactNode[] {
	return runs.map((run, index) => {
		const key = `${keyPrefix}-${index}`;

		if (run.type === "strong") {
			return (
				<strong key={key} className="font-semibold">
					{renderRuns(run.children, context, key)}
				</strong>
			);
		}

		if (run.type === "code") {
			return (
				<code
					key={key}
					dir="ltr"
					className="isolate-ltr rounded bg-gray-100 px-1 font-mono text-[0.85em] text-gray-800"
				>
					{run.value}
				</code>
			);
		}

		return <span key={key}>{renderText(run.value, context, key)}</span>;
	});
}

function renderText(
	value: string,
	context: RenderContext,
	keyPrefix: string,
): React.ReactNode[] {
	return parseAnswerSegments(value).map((segment) => {
		if (segment.type === "text") {
			return (
				<span key={`${keyPrefix}-text-${segment.offset}`}>{segment.value}</span>
			);
		}

		const citation = context.citationsByChunkId.get(segment.chunkId);

		if (!citation) {
			return (
				<span key={`${keyPrefix}-marker-${segment.offset}`}>{segment.raw}</span>
			);
		}

		return (
			<button
				key={`${keyPrefix}-marker-${segment.offset}`}
				type="button"
				dir="ltr"
				onClick={() => context.onCitationClick(citation)}
				title={context.openSource(citation.filename)}
				aria-label={context.openCitation(segment.chunkId)}
				className="isolate-ltr mx-0.5 inline-flex items-center rounded bg-blue-50 px-1 text-xs font-semibold leading-none text-blue-700 transition hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-blue-300"
			>
				{segment.raw}
			</button>
		);
	});
}

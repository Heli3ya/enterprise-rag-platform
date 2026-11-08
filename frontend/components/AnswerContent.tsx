"use client";

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

/**
 * Render an assistant answer with the `[n]` markers turned into
 * buttons. Markers without a matching citation stay plain text, so a
 * hallucinated or filtered-out id is visible but not clickable.
 */
export default function AnswerContent({
	content,
	citations,
	onCitationClick,
}: AnswerContentProps) {
	const t = useT();
	const citationsByChunkId = indexCitations(citations);
	const segments = parseAnswerSegments(content);

	return (
		<p className="whitespace-pre-wrap text-sm leading-6">
			{segments.map((segment) => {
				if (segment.type === "text") {
					return <span key={`text-${segment.offset}`}>{segment.value}</span>;
				}

				const citation = citationsByChunkId.get(segment.chunkId);

				if (!citation) {
					return <span key={`marker-${segment.offset}`}>{segment.raw}</span>;
				}

				return (
					<button
						key={`marker-${segment.offset}`}
						type="button"
						onClick={() => onCitationClick(citation)}
						title={`${t("Open source")}: ${citation.filename}`}
						aria-label={`${t("Open citation")} [${segment.chunkId}]`}
						className="mx-0.5 inline-flex items-center rounded bg-blue-50 px-1 text-xs font-semibold leading-none text-blue-700 transition hover:bg-blue-100 focus:outline-none focus:ring-2 focus:ring-blue-300"
					>
						{segment.raw}
					</button>
				);
			})}
		</p>
	);
}

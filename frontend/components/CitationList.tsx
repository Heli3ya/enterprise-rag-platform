"use client";

import { type Citation, citationLabel } from "../lib/citations";
import { useT } from "./PreferencesProvider";

type CitationListProps = {
	citations: Citation[];
	onCitationClick: (citation: Citation) => void;
};

/**
 * Source cards under an answer. The badge shows the chunk id, which
 * is exactly the number used by the `[n]` markers in the answer text,
 * so a user can match a marker to its card.
 */
export default function CitationList({
	citations,
	onCitationClick,
}: CitationListProps) {
	const t = useT();

	if (citations.length === 0) {
		return null;
	}

	return (
		<div className="mt-4 border-t border-gray-200 pt-3">
			<p className="mb-2 text-xs font-semibold text-gray-500">{t("Sources")}</p>

			<div className="flex flex-col gap-2">
				{citations.map((citation) => (
					<button
						key={`${citation.document_id}-${citation.chunk_id}`}
						type="button"
						onClick={() => onCitationClick(citation)}
						aria-label={`${t("Source")} [${citation.chunk_id}] ${citationLabel(citation)}`}
						className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-start transition hover:border-blue-300 hover:bg-blue-50"
					>
						<span className="flex items-center gap-2">
							<span className="rounded bg-blue-100 px-1.5 py-0.5 text-[11px] font-semibold text-blue-700">
								[{citation.chunk_id}]
							</span>

							<span className="truncate text-xs font-medium text-gray-800">
								{citationLabel(citation)}
							</span>
						</span>

						<span className="mt-1 block text-[11px] text-gray-500">
							{citation.department}
							{citation.chunk_index !== undefined
								? ` · ${t("Chunk {index}", {
										index: citation.chunk_index + 1,
									})}`
								: ""}
						</span>

						{citation.snippet && (
							<span className="mt-1 block line-clamp-2 text-[11px] leading-5 text-gray-600">
								{citation.snippet}
							</span>
						)}
					</button>
				))}
			</div>
		</div>
	);
}

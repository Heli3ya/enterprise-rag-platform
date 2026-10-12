"use client";

type Citation = {
	document_id: number;
	filename: string;
	department: string;
	chunk_id: number;
};

type CitationListProps = {
	citations: Citation[];
	onCitationClick: (citation: Citation) => void;
};

export default function CitationList({
	citations,
	onCitationClick,
}: CitationListProps) {
	if (citations.length === 0) {
		return null;
	}

	return (
		<div className="mt-4 border-t border-gray-200 pt-3">
			<p className="mb-2 text-xs font-semibold text-gray-500">Sources</p>

			<div className="flex flex-wrap gap-2">
				{citations.map((citation) => (
					<button
						key={`${citation.document_id}-${citation.chunk_id}`}
						type="button"
						onClick={() => onCitationClick(citation)}
						className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-left text-xs transition hover:border-blue-300 hover:bg-blue-50"
					>
						<p className="font-medium text-gray-800">{citation.filename}</p>

						<p className="mt-1 text-gray-500">
							Department: {citation.department}
						</p>
					</button>
				))}
			</div>
		</div>
	);
}

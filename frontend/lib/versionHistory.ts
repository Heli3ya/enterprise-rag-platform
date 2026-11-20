/**
 * Types and pure helpers for `GET /api/documents/{id}/versions/`.
 *
 * The backend already returns the whole chain in chronological order, but
 * the UI does not trust that blindly: sorting here makes the modal stable
 * even if a proxy reorders rows, and keeps this module trivially testable
 * with the Node test runner.
 */

export type VersionEntry = {
	id: number;
	version: number;
	title?: string;
	status?: string;
	file_size?: number | null;
	created_at?: string | null;
	archived_at?: string | null;
	purged_at?: string | null;
	is_current?: boolean;
};

export type VersionHistoryResponse = {
	document_id: number;
	version: number;
	latest_document_id?: number | null;
	versions: VersionEntry[];
};

function isVersionEntry(value: unknown): value is VersionEntry {
	if (!value || typeof value !== "object") {
		return false;
	}

	const entry = value as Record<string, unknown>;

	return (
		typeof entry.id === "number" &&
		typeof entry.version === "number" &&
		entry.version >= 1
	);
}

export function normalizeVersionHistory(data: unknown): VersionEntry[] {
	const entries = Array.isArray(data)
		? data
		: data &&
				typeof data === "object" &&
				Array.isArray((data as { versions?: unknown }).versions)
			? (data as { versions: unknown[] }).versions
			: [];

	return entries
		.filter(isVersionEntry)
		.slice()
		.sort((left, right) => left.version - right.version);
}

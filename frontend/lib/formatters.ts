/** Shared display formatters so tables and dialogs stay consistent. */

export function formatFileSize(size?: number | null): string {
	if (size === undefined || size === null || size <= 0) {
		return "—";
	}

	if (size < 1024) {
		return `${size} B`;
	}

	if (size < 1024 * 1024) {
		return `${(size / 1024).toFixed(1)} KB`;
	}

	return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * UTC keeps the output identical on a developer laptop and in CI. The API
 * stores UTC timestamps, and version history is about *when* something was
 * uploaded, not about the viewer's timezone arithmetic.
 */
export function formatDateTime(value?: string | null, locale = "en"): string {
	if (!value) {
		return "—";
	}

	const date = new Date(value);

	if (Number.isNaN(date.getTime())) {
		return "—";
	}

	return new Intl.DateTimeFormat(locale, {
		dateStyle: "medium",
		timeStyle: "short",
		timeZone: "UTC",
	}).format(date);
}

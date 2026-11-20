/**
 * Upload formats — single source of truth for the browser-side gate and the
 * icons shown in the drop zone.
 *
 * The server (`documents/filetypes.py`) still decides what a file really is
 * by reading its bytes. This list only makes obvious mistakes fail before a
 * network round-trip, so MIME types are deliberately permissive: browsers
 * label the same CSV as `text/csv`, `application/vnd.ms-excel`, or even
 * `application/octet-stream`.
 *
 * Keeping the groups, the `accept` attribute and the validation gate in one
 * module prevents the regression that already happened once in this project:
 * `.xlsx` was added to the input and the server but forgotten in the JS
 * filter, so valid files never left the browser.
 */

export type UploadFormatKey =
	| "pdf"
	| "word"
	| "text"
	| "excel"
	| "email"
	| "image";

export type UploadFormatGroup = {
	key: UploadFormatKey;
	/** English source string; translated through `t()` in the UI. */
	label: string;
	/** Emoji glyph so the guidance needs no icon dependency. */
	icon: string;
	extensions: readonly string[];
	mimeTypes: readonly string[];
};

export const UPLOAD_FORMAT_GROUPS: readonly UploadFormatGroup[] = [
	{
		key: "pdf",
		label: "PDF",
		icon: "📕",
		extensions: [".pdf"],
		mimeTypes: ["application/pdf"],
	},
	{
		key: "word",
		label: "Word",
		icon: "📘",
		extensions: [".doc", ".docx"],
		mimeTypes: [
			"application/msword",
			"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
		],
	},
	{
		key: "text",
		label: "TXT",
		icon: "📄",
		extensions: [".txt"],
		mimeTypes: ["text/plain"],
	},
	{
		key: "excel",
		label: "Excel / CSV",
		icon: "📗",
		extensions: [".xlsx", ".csv"],
		mimeTypes: [
			"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
			"application/vnd.ms-excel",
			"text/csv",
		],
	},
	{
		key: "email",
		label: "Email",
		icon: "✉️",
		extensions: [".eml"],
		mimeTypes: ["message/rfc822"],
	},
	{
		key: "image",
		label: "Images",
		icon: "🖼️",
		extensions: [".jpg", ".jpeg", ".png"],
		mimeTypes: ["image/jpeg", "image/png"],
	},
];

/** Browser MIME label used when the OS has no specific mapping. */
const FALLBACK_MIME_TYPE = "application/octet-stream";

export const ALLOWED_EXTENSIONS: readonly string[] =
	UPLOAD_FORMAT_GROUPS.flatMap((group) => [...group.extensions]);

export const ALLOWED_MIME_TYPES: readonly string[] = [
	...UPLOAD_FORMAT_GROUPS.flatMap((group) => [...group.mimeTypes]),
	FALLBACK_MIME_TYPE,
];

/** The value for both `<input type="file" accept=...>` elements. */
export const UPLOAD_ACCEPT = ALLOWED_EXTENSIONS.join(",");

export function isAllowedUploadFile(name: string, mimeType = ""): boolean {
	const lowerName = name.toLowerCase();
	const extensionAllowed = ALLOWED_EXTENSIONS.some((extension) =>
		lowerName.endsWith(extension),
	);

	const mimeAllowed = !mimeType || ALLOWED_MIME_TYPES.includes(mimeType);

	return extensionAllowed && mimeAllowed;
}

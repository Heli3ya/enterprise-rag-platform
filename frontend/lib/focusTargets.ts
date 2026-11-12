/**
 * Focus targets shared by the cold-start empty state and the chat.
 *
 * Both the dashboard banner and an inline "no documents" answer need to
 * move the user to the uploader or back to the input. Passing a ref
 * through three components for a scroll-and-focus would add more
 * plumbing than value, so the two elements expose stable ids and these
 * helpers own the interaction.
 */

export const UPLOAD_SECTION_ID = "document-upload";
export const UPLOAD_TRIGGER_ID = "document-upload-trigger";
export const CHAT_INPUT_ID = "chat-input";

function focusById(id: string) {
	if (typeof document === "undefined") {
		return;
	}

	document.getElementById(id)?.focus({ preventScroll: true });
}

/** Scroll to the uploader and put the keyboard on its drop zone. */
export function focusDocumentUploader() {
	if (typeof document === "undefined") {
		return;
	}

	document
		.getElementById(UPLOAD_SECTION_ID)
		?.scrollIntoView({ behavior: "smooth", block: "start" });

	focusById(UPLOAD_TRIGGER_ID);
}

/** Return the user to the question box. */
export function focusChatInput() {
	focusById(CHAT_INPUT_ID);
}

/**
 * Client side of the answer feedback loop.
 *
 * `POST /api/chat/feedback/` is idempotent per (answer, user) at the
 * database level, so the UI treats `409` as success: the answer already
 * carries a verdict, which is exactly the state the user is trying to
 * reach. Mapping it to an error would only invite pointless retries.
 */

import { API_BASE_URL, authorizedFetch, readErrorMessage } from "./api";

export type FeedbackVerdict = "up" | "down";

/** Mirrors `FeedbackCreateSerializer.user_comment` on the server. */
export const MAX_COMMENT_LENGTH = 2000;

export type FeedbackFailureReason =
	| "not_found"
	| "unauthorized"
	| "forbidden"
	| "invalid"
	| "rate_limited"
	| "network"
	| "server";

export type FeedbackResult =
	| { ok: true; alreadyRated: boolean }
	| { ok: false; reason: FeedbackFailureReason; message: string };

type SubmitArgs = {
	answerId: string;
	verdict: FeedbackVerdict;
	comment?: string;
};

/**
 * Send one verdict for one answer.
 *
 * Never throws: every failure becomes a typed result so the component can
 * pick a translation instead of showing a raw server string.
 */
export async function submitAnswerFeedback({
	answerId,
	verdict,
	comment = "",
}: SubmitArgs): Promise<FeedbackResult> {
	let response: Response;

	try {
		response = await authorizedFetch(`${API_BASE_URL}/chat/feedback/`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({
				answer_id: answerId,
				is_positive: verdict === "up",
				// Trim and cap on the client too: the server rejects longer
				// values, and a silently truncated comment is friendlier
				// than a 400 after the user typed a paragraph.
				user_comment: comment.trim().slice(0, MAX_COMMENT_LENGTH),
			}),
		});
	} catch (error) {
		const message = error instanceof Error ? error.message : "";

		return {
			ok: false,
			reason: message.toLowerCase().includes("session")
				? "unauthorized"
				: "network",
			message,
		};
	}

	if (response.status === 201) {
		return { ok: true, alreadyRated: false };
	}

	if (response.status === 409) {
		return { ok: true, alreadyRated: true };
	}

	const message = await readErrorMessage(response);

	switch (response.status) {
		case 400:
			return { ok: false, reason: "invalid", message };
		case 401:
			return { ok: false, reason: "unauthorized", message };
		case 403:
			return { ok: false, reason: "forbidden", message };
		case 404:
			return { ok: false, reason: "not_found", message };
		case 429:
			return { ok: false, reason: "rate_limited", message };
		default:
			return { ok: false, reason: "server", message };
	}
}

/**
 * Remember which answers this browser already rated.
 *
 * The server is the source of truth; this is only a UI hint so a reload
 * does not resurrect the buttons for an answer that was already rated.
 * The list is capped, oldest first, to keep localStorage small forever.
 */
const RATED_STORAGE_KEY = "chat_feedback_rated";
const RATED_LIMIT = 200;

function readRated(): string[] {
	if (typeof window === "undefined") {
		return [];
	}

	try {
		const raw = window.localStorage.getItem(RATED_STORAGE_KEY);
		const parsed: unknown = raw ? JSON.parse(raw) : null;

		return Array.isArray(parsed)
			? parsed.filter((value): value is string => typeof value === "string")
			: [];
	} catch {
		return [];
	}
}

export function isAnswerRated(answerId: string): boolean {
	return readRated().includes(answerId);
}

export function rememberRatedAnswer(answerId: string): void {
	if (typeof window === "undefined") {
		return;
	}

	try {
		const rated = readRated().filter((id) => id !== answerId);

		rated.push(answerId);

		window.localStorage.setItem(
			RATED_STORAGE_KEY,
			JSON.stringify(rated.slice(-RATED_LIMIT)),
		);
	} catch {
		// Private mode or a full quota: the hint simply does not persist.
	}
}

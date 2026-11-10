"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
	type FeedbackFailureReason,
	type FeedbackVerdict,
	isAnswerRated,
	MAX_COMMENT_LENGTH,
	rememberRatedAnswer,
	submitAnswerFeedback,
} from "../lib/feedback";
import { useT } from "./PreferencesProvider";

type Phase = "idle" | "submitting" | "done" | "error";

/**
 * One translated sentence per server outcome.
 *
 * The reason is stored in state and translated at render time, so
 * switching language re-renders the error in the new language instead of
 * freezing the message in whichever language it was shown in.
 */
const FAILURE_MESSAGES: Record<FeedbackFailureReason, string> = {
	not_found: "This answer is no longer available.",
	unauthorized: "Your session has expired. Please sign in again.",
	forbidden: "You do not have access to rate this answer.",
	invalid: "That feedback could not be saved. Please try again.",
	rate_limited: "Too many feedback attempts. Please try again later.",
	network: "Could not reach the server. Please try again.",
	server: "Could not send your feedback. Please try again.",
};

function ThumbsUpIcon({ className }: { className?: string }) {
	return (
		<svg
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			strokeWidth={1.8}
			strokeLinecap="round"
			strokeLinejoin="round"
			className={className}
			aria-hidden="true"
		>
			<path d="M7 10v12" />
			<path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" />
		</svg>
	);
}

function ThumbsDownIcon({ className }: { className?: string }) {
	return (
		<svg
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			strokeWidth={1.8}
			strokeLinecap="round"
			strokeLinejoin="round"
			className={className}
			aria-hidden="true"
		>
			<path d="M17 14V2" />
			<path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z" />
		</svg>
	);
}

type AnswerFeedbackProps = {
	/** UUID from the `meta` event of the chat stream. */
	answerId: string | null;
};

/**
 * Thumbs up / thumbs down under one assistant answer.
 *
 * Thumbs up is a single click and one request. Thumbs down opens an
 * optional comment box first, so a negative signal arrives with a reason
 * instead of a bare boolean — that reason is what makes the data usable
 * for reranker tuning and fine-tuning later.
 */
export default function AnswerFeedback({ answerId }: AnswerFeedbackProps) {
	const t = useT();
	const textareaId = useId();

	const [phase, setPhase] = useState<Phase>("idle");
	const [verdict, setVerdict] = useState<FeedbackVerdict | null>(null);
	const [commentOpen, setCommentOpen] = useState(false);
	const [comment, setComment] = useState("");
	const [failure, setFailure] = useState<FeedbackFailureReason | null>(null);

	const mounted = useRef(true);
	const inFlight = useRef(false);
	const commentRef = useRef<HTMLTextAreaElement | null>(null);

	useEffect(() => {
		mounted.current = true;

		return () => {
			mounted.current = false;
		};
	}, []);

	// Opening the box is an explicit user action, so moving the caret into
	// it is expected. Done in an effect rather than with `autoFocus` to
	// keep the accessibility linter (and iOS keyboard heuristics) happy.
	useEffect(() => {
		if (commentOpen) {
			commentRef.current?.focus();
		}
	}, [commentOpen]);

	// The rated list lives in localStorage, which is not readable during
	// SSR. Reading it in an effect keeps hydration identical and avoids
	// resurfacing the buttons for an answer this browser already rated.
	useEffect(() => {
		if (answerId && isAnswerRated(answerId)) {
			setPhase("done");
		}
	}, [answerId]);

	const send = useCallback(
		async (chosen: FeedbackVerdict, text: string) => {
			// A ref, not state: two clicks in the same tick would both read
			// the pre-update `phase` and fire two requests.
			if (!answerId || inFlight.current) {
				return;
			}

			inFlight.current = true;
			setVerdict(chosen);
			setPhase("submitting");
			setFailure(null);

			const result = await submitAnswerFeedback({
				answerId,
				verdict: chosen,
				comment: text,
			});

			inFlight.current = false;

			if (!mounted.current) {
				return;
			}

			if (result.ok) {
				rememberRatedAnswer(answerId);
				setPhase("done");
				setCommentOpen(false);
				return;
			}

			setPhase("error");
			setFailure(result.reason);
		},
		[answerId],
	);

	const handlePositive = () => {
		if (phase === "submitting" || phase === "done") {
			return;
		}

		// Switching from a negative attempt: the reason no longer applies.
		setCommentOpen(false);
		void send("up", "");
	};

	const handleNegative = () => {
		if (phase === "submitting" || phase === "done") {
			return;
		}

		setVerdict("down");
		setCommentOpen(true);
		setFailure(null);
		setPhase("idle");
	};

	const handleSubmitComment = (event: React.FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		void send("down", comment);
	};

	const handleCancel = () => {
		setCommentOpen(false);
		setComment("");
		setVerdict(null);
		setFailure(null);
		setPhase("idle");
	};

	if (!answerId) {
		return null;
	}

	const busy = phase === "submitting";
	const settled = phase === "done";

	const buttonClass = (active: boolean, tone: "positive" | "negative") => {
		if (active && tone === "positive") {
			return "border-green-200 bg-green-50 text-green-700";
		}

		if (active && tone === "negative") {
			return "border-red-200 bg-red-50 text-red-700";
		}

		return "border-gray-200 bg-white text-gray-500 hover:bg-gray-100 hover:text-gray-800";
	};

	return (
		<div className="mt-3 border-t border-gray-200 pt-3">
			<div className="flex flex-wrap items-center gap-2">
				<span className="text-xs font-medium text-gray-500">
					{t("Was this answer helpful?")}
				</span>

				<fieldset className="m-0 flex items-center gap-1 border-0 p-0">
					<legend className="sr-only">{t("Rate this answer")}</legend>
					<button
						type="button"
						onClick={handlePositive}
						disabled={busy || settled}
						aria-pressed={verdict === "up"}
						aria-label={t("Helpful")}
						title={t("Helpful")}
						className={`inline-flex h-8 w-8 items-center justify-center rounded-lg border transition focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 disabled:cursor-not-allowed disabled:opacity-60 ${buttonClass(
							verdict === "up",
							"positive",
						)}`}
					>
						<ThumbsUpIcon className="h-4 w-4" />
					</button>

					<button
						type="button"
						onClick={handleNegative}
						disabled={busy || settled}
						aria-pressed={verdict === "down"}
						aria-expanded={commentOpen}
						aria-label={t("Not helpful")}
						title={t("Not helpful")}
						className={`inline-flex h-8 w-8 items-center justify-center rounded-lg border transition focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-300 disabled:cursor-not-allowed disabled:opacity-60 ${buttonClass(
							verdict === "down",
							"negative",
						)}`}
					>
						<ThumbsDownIcon className="h-4 w-4" />
					</button>
				</fieldset>

				{busy && (
					<span className="text-xs text-gray-400">
						{t("Saving your feedback...")}
					</span>
				)}

				{settled && (
					<span role="status" className="text-xs font-medium text-green-700">
						{t("Thanks for your feedback.")}
					</span>
				)}
			</div>

			{commentOpen && !settled && (
				<form
					onSubmit={handleSubmitComment}
					className="mt-3 rounded-lg border border-gray-200 bg-gray-50 p-3"
				>
					<label
						htmlFor={textareaId}
						className="block text-xs font-semibold text-gray-700"
					>
						{t("What went wrong with this answer?")}
					</label>

					<p className="mt-1 text-[11px] text-gray-500">
						{t("Optional — your note helps us improve the answers.")}
					</p>

					<textarea
						id={textareaId}
						ref={commentRef}
						value={comment}
						onChange={(event) => setComment(event.target.value)}
						rows={2}
						maxLength={MAX_COMMENT_LENGTH}
						disabled={busy}
						placeholder={t(
							"Missing information, wrong source, unclear wording...",
						)}
						className="mt-2 w-full resize-none rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-800 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-gray-100"
					/>

					<div className="mt-2 flex items-center justify-between gap-2">
						<span className="text-[11px] text-gray-400">
							{comment.length >= MAX_COMMENT_LENGTH - 200
								? `${comment.length}/${MAX_COMMENT_LENGTH}`
								: ""}
						</span>

						<div className="flex items-center gap-2">
							<button
								type="button"
								onClick={handleCancel}
								disabled={busy}
								className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 transition hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-60"
							>
								{t("Cancel")}
							</button>

							<button
								type="submit"
								disabled={busy}
								className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
							>
								{busy ? t("Saving...") : t("Submit feedback")}
							</button>
						</div>
					</div>
				</form>
			)}

			{failure && phase === "error" && (
				<p role="alert" className="mt-2 text-xs text-red-600">
					{t(FAILURE_MESSAGES[failure])}
				</p>
			)}
		</div>
	);
}

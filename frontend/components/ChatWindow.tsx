"use client";

import { useRef, useState } from "react";
import { API_BASE_URL, authorizedFetch, readErrorMessage } from "../lib/api";
import type { Citation } from "../lib/citations";
import AnswerContent from "./AnswerContent";
import CitationList from "./CitationList";
import CitationPanel from "./CitationPanel";
import { useT } from "./PreferencesProvider";

/** Rendered through `t()` so the greeting follows the selected language. */
const GREETING =
	"Hello! I am your Enterprise RAG Assistant. How can I help you?";

type Message = {
	id: number;
	role: "user" | "assistant";
	content: string;
	isLoading?: boolean;
	citations?: Citation[];
	/** The question behind an assistant answer, used to highlight sources. */
	question?: string;
};

type ActiveSource = {
	citation: Citation;
	query: string;
};

export default function ChatWindow() {
	const t = useT();

	const [messages, setMessages] = useState<Message[]>([
		{
			id: 1,
			role: "assistant",
			content: GREETING,
		},
	]);

	const [input, setInput] = useState("");
	const [isLoading, setIsLoading] = useState(false);

	// The citation currently open in the source drawer, plus the
	// question that produced it (needed to highlight the match).
	const [activeSource, setActiveSource] = useState<ActiveSource | null>(null);

	const conversationId = useRef(
		"conversation-" +
			Date.now() +
			"-" +
			Math.random().toString(36).slice(2, 10),
	);

	const handleCitationClick = (citation: Citation, query: string) => {
		setActiveSource({ citation, query });
	};

	const closeCitationPanel = () => {
		setActiveSource(null);
	};

	const handleSend = async () => {
		const question = input.trim();

		if (!question || isLoading) {
			return;
		}

		const userMessage: Message = {
			id: Date.now(),
			role: "user",
			content: question,
		};

		const assistantMessageId = Date.now() + 1;

		const assistantMessage: Message = {
			id: assistantMessageId,
			role: "assistant",
			content: "",
			isLoading: true,
			citations: [],
			question,
		};

		setMessages((currentMessages) => [
			...currentMessages,
			userMessage,
			assistantMessage,
		]);

		setInput("");
		setIsLoading(true);

		try {
			const response = await authorizedFetch(`${API_BASE_URL}/chat/ask/`, {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
				},
				body: JSON.stringify({
					question: question,
					conversation_id: conversationId.current,
				}),
			});

			if (!response.ok) {
				throw new Error(await readErrorMessage(response));
			}

			if (!response.body) {
				throw new Error(t("Streaming response is not available."));
			}

			const reader = response.body.getReader();
			const decoder = new TextDecoder("utf-8");

			let buffer = "";

			while (true) {
				const result = await reader.read();

				if (result.done) {
					break;
				}

				const value = result.value;

				buffer += decoder.decode(value, {
					stream: true,
				});

				const events = buffer.split("\n\n");

				buffer = events.pop() || "";

				for (const event of events) {
					const lines = event.split("\n");

					let eventType = "";
					let eventData = "";

					for (const line of lines) {
						if (line.startsWith("event:")) {
							eventType = line.slice("event:".length).trim();
						}

						if (line.startsWith("data:")) {
							eventData += line.slice("data:".length).trim();
						}
					}

					if (!eventType || !eventData) {
						continue;
					}

					if (eventType === "error") {
						let message = t("An error occurred during the chat.");

						try {
							const data = JSON.parse(eventData);
							message = data.error || message;
						} catch {
							// Keep the generic message for malformed payloads.
						}

						throw new Error(message);
					}

					let data: unknown = null;

					try {
						data = JSON.parse(eventData);
					} catch {
						// Ignore a single malformed event instead of aborting
						// the whole answer.
						continue;
					}

					if (eventType === "token") {
						const tokenPayload = data as { content?: string };

						setMessages((currentMessages) =>
							currentMessages.map((message) => {
								if (message.id !== assistantMessageId) {
									return message;
								}

								return {
									...message,
									content: message.content + (tokenPayload.content || ""),
									isLoading: false,
								};
							}),
						);
					}

					if (eventType === "citations") {
						setMessages((currentMessages) =>
							currentMessages.map((message) => {
								if (message.id !== assistantMessageId) {
									return message;
								}

								return {
									...message,
									citations: Array.isArray(data) ? data : [],
								};
							}),
						);
					}

					if (eventType === "done") {
						setMessages((currentMessages) =>
							currentMessages.map((message) => {
								if (message.id !== assistantMessageId) {
									return message;
								}

								return {
									...message,
									isLoading: false,
								};
							}),
						);
					}
				}
			}

			setMessages((currentMessages) =>
				currentMessages.map((message) => {
					if (message.id !== assistantMessageId) {
						return message;
					}

					return {
						...message,
						isLoading: false,
					};
				}),
			);

			setIsLoading(false);
		} catch (error) {
			const errorMessage =
				error instanceof Error
					? error.message
					: t("An unexpected error occurred.");

			setMessages((currentMessages) =>
				currentMessages.map((message) => {
					if (message.id !== assistantMessageId) {
						return message;
					}

					return {
						...message,
						content: `${t("Sorry, an error occurred:")} ${errorMessage}`,
						isLoading: false,
					};
				}),
			);

			setIsLoading(false);
		}
	};

	const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
		if (event.key === "Enter" && !event.shiftKey) {
			event.preventDefault();
			handleSend();
		}
	};

	return (
		<section className="mt-8 overflow-hidden rounded-xl bg-white shadow-lg">
			<div className="border-b border-gray-200 px-6 py-4">
				<h2 className="text-lg font-semibold text-gray-800">
					{t("Chat Assistant")}
				</h2>

				<p className="mt-1 text-sm text-gray-500">
					{t("Ask questions about your enterprise documents")}
				</p>
			</div>

			<div className="h-[450px] overflow-y-auto bg-gray-50 p-6">
				<div className="space-y-4">
					{messages.map((message) => (
						<div
							key={message.id}
							className={
								message.role === "user"
									? "flex justify-end"
									: "flex justify-start"
							}
						>
							<div
								className={
									message.role === "user"
										? "max-w-[80%] rounded-2xl rounded-ee-md bg-blue-600 px-4 py-3 text-white"
										: "max-w-[80%] rounded-2xl rounded-es-md bg-white px-4 py-3 text-gray-800 shadow-sm"
								}
							>
								<p className="mb-1 text-xs font-semibold opacity-70">
									{message.role === "user" ? t("You") : t("Assistant")}
								</p>

								{message.content ? (
									message.role === "assistant" ? (
										<AnswerContent
											content={
												message.content === GREETING
													? t(GREETING)
													: message.content
											}
											citations={message.citations}
											onCitationClick={(citation) =>
												handleCitationClick(citation, message.question ?? "")
											}
										/>
									) : (
										<p className="whitespace-pre-wrap text-sm leading-6">
											{message.content}
										</p>
									)
								) : message.isLoading ? (
									<div className="flex items-center gap-1 py-1">
										<span className="h-2 w-2 animate-bounce rounded-full bg-gray-400 [animation-delay:-0.3s]" />
										<span className="h-2 w-2 animate-bounce rounded-full bg-gray-400 [animation-delay:-0.15s]" />
										<span className="h-2 w-2 animate-bounce rounded-full bg-gray-400" />
									</div>
								) : null}

								{message.role === "assistant" &&
									message.citations &&
									message.citations.length > 0 && (
										<CitationList
											citations={message.citations}
											onCitationClick={(citation) =>
												handleCitationClick(citation, message.question ?? "")
											}
										/>
									)}
							</div>
						</div>
					))}
				</div>
			</div>

			<div className="border-t border-gray-200 bg-white p-4">
				<div className="flex items-end gap-3">
					<textarea
						value={input}
						onChange={(event) => setInput(event.target.value)}
						onKeyDown={handleKeyDown}
						placeholder={t("Type your question...")}
						rows={2}
						disabled={isLoading}
						className="min-h-[52px] flex-1 resize-none rounded-xl border border-gray-300 px-4 py-3 text-sm text-gray-800 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-gray-100"
					/>

					<button
						type="button"
						onClick={handleSend}
						disabled={!input.trim() || isLoading}
						className="rounded-xl bg-blue-600 px-5 py-3 font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
					>
						{isLoading ? t("Sending...") : t("Send")}
					</button>
				</div>

				<p className="mt-2 text-xs text-gray-400">
					{t("Press Enter to send · Shift + Enter for a new line")}
				</p>
			</div>

			<CitationPanel
				citation={activeSource?.citation ?? null}
				query={activeSource?.query ?? ""}
				onClose={closeCitationPanel}
			/>
		</section>
	);
}

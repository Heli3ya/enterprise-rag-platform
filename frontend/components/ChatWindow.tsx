"use client";

import { useRef, useState } from "react";
import CitationList from "./CitationList";

type Citation = {
	document_id: number;
	filename: string;
	department: string;
	chunk_id: number;
};

type Message = {
	id: number;
	role: "user" | "assistant";
	content: string;
	isLoading?: boolean;
	citations?: Citation[];
};

type DocumentMetadata = {
	id: number;
	title: string;
	file_type: string;
	status: string;
	department: number;
	uploaded_by: number;
	created_at: string;
};

const API_BASE_URL =
	process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000/api";

export default function ChatWindow() {
	const [messages, setMessages] = useState<Message[]>([
		{
			id: 1,
			role: "assistant",
			content: "Hello! I am your Enterprise RAG Assistant. How can I help you?",
		},
	]);

	const [input, setInput] = useState("");
	const [isLoading, setIsLoading] = useState(false);

	const [selectedDocument, setSelectedDocument] =
		useState<DocumentMetadata | null>(null);

	const [isDocumentLoading, setIsDocumentLoading] = useState(false);

	const [documentError, setDocumentError] = useState("");

	const conversationId = useRef(
		"conversation-" +
			Date.now() +
			"-" +
			Math.random().toString(36).slice(2, 10),
	);

	const handleCitationClick = async (citation: Citation) => {
		setIsDocumentLoading(true);
		setDocumentError("");
		setSelectedDocument(null);

		try {
			const accessToken = localStorage.getItem("access_token");

			if (!accessToken) {
				throw new Error("Authentication token not found.");
			}

			const response = await fetch(
				`${API_BASE_URL}/documents/${citation.document_id}/`,
				{
					method: "GET",
					headers: {
						Authorization: `Bearer ${accessToken}`,
					},
				},
			);

			if (!response.ok) {
				const errorText = await response.text();

				throw new Error(errorText || "Failed to load document metadata.");
			}

			const data: DocumentMetadata = await response.json();

			setSelectedDocument(data);
		} catch (error) {
			const errorMessage =
				error instanceof Error
					? error.message
					: "An unexpected error occurred.";

			setDocumentError(errorMessage);
		} finally {
			setIsDocumentLoading(false);
		}
	};

	const closeDocumentMetadata = () => {
		setSelectedDocument(null);
		setDocumentError("");
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
		};

		setMessages((currentMessages) => [
			...currentMessages,
			userMessage,
			assistantMessage,
		]);

		setInput("");
		setIsLoading(true);

		try {
			const accessToken = localStorage.getItem("access_token");

			if (!accessToken) {
				throw new Error("Authentication token not found.");
			}

			const response = await fetch(`${API_BASE_URL}/chat/ask/`, {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
					Authorization: `Bearer ${accessToken}`,
				},
				body: JSON.stringify({
					question: question,
					conversation_id: conversationId.current,
				}),
			});

			if (!response.ok) {
				const errorText = await response.text();

				throw new Error(
					errorText || "Failed to get a response from the server.",
				);
			}

			if (!response.body) {
				throw new Error("Streaming response is not available.");
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

					if (eventType === "token") {
						const data = JSON.parse(eventData);

						setMessages((currentMessages) =>
							currentMessages.map((message) => {
								if (message.id !== assistantMessageId) {
									return message;
								}

								return {
									...message,
									content: message.content + (data.content || ""),
									isLoading: false,
								};
							}),
						);
					}

					if (eventType === "citations") {
						const data = JSON.parse(eventData);

						console.log("Chat citations:", data);

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

					if (eventType === "error") {
						const data = JSON.parse(eventData);

						throw new Error(data.error || "An error occurred during the chat.");
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
					: "An unexpected error occurred.";

			setMessages((currentMessages) =>
				currentMessages.map((message) => {
					if (message.id !== assistantMessageId) {
						return message;
					}

					return {
						...message,
						content: `Sorry, an error occurred: ${errorMessage}`,
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
				<h2 className="text-lg font-semibold text-gray-800">Chat Assistant</h2>

				<p className="mt-1 text-sm text-gray-500">
					Ask questions about your enterprise documents
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
										? "max-w-[80%] rounded-2xl rounded-br-md bg-blue-600 px-4 py-3 text-white"
										: "max-w-[80%] rounded-2xl rounded-bl-md bg-white px-4 py-3 text-gray-800 shadow-sm"
								}
							>
								<p className="mb-1 text-xs font-semibold opacity-70">
									{message.role === "user" ? "You" : "Assistant"}
								</p>

								{message.content ? (
									<p className="whitespace-pre-wrap text-sm leading-6">
										{message.content}
									</p>
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
											onCitationClick={handleCitationClick}
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
						placeholder="Type your question..."
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
						{isLoading ? "Sending..." : "Send"}
					</button>
				</div>

				<p className="mt-2 text-xs text-gray-400">
					Press Enter to send · Shift + Enter for a new line
				</p>
			</div>

			{(isDocumentLoading || documentError) && (
				<div className="border-t border-gray-200 bg-white p-4">
					{isDocumentLoading && (
						<p className="text-sm text-gray-500">Loading document details...</p>
					)}

					{documentError && (
						<p className="text-sm text-red-600">{documentError}</p>
					)}
				</div>
			)}

			{selectedDocument && (
				<div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
					<div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
						<div className="flex items-center justify-between">
							<h3 className="text-lg font-semibold text-gray-800">
								Document Details
							</h3>

							<button
								type="button"
								onClick={closeDocumentMetadata}
								className="rounded-md px-2 py-1 text-gray-500 transition hover:bg-gray-100 hover:text-gray-800"
							>
								X
							</button>
						</div>

						<div className="mt-5 space-y-3">
							<div>
								<p className="text-xs font-semibold text-gray-500">Title</p>

								<p className="mt-1 text-sm text-gray-800">
									{selectedDocument.title}
								</p>
							</div>

							<div>
								<p className="text-xs font-semibold text-gray-500">File Type</p>

								<p className="mt-1 text-sm text-gray-800">
									{selectedDocument.file_type}
								</p>
							</div>

							<div>
								<p className="text-xs font-semibold text-gray-500">Status</p>

								<p className="mt-1 text-sm text-gray-800">
									{selectedDocument.status}
								</p>
							</div>

							<div>
								<p className="text-xs font-semibold text-gray-500">
									Department ID
								</p>

								<p className="mt-1 text-sm text-gray-800">
									{selectedDocument.department}
								</p>
							</div>

							<div>
								<p className="text-xs font-semibold text-gray-500">
									Uploaded By
								</p>

								<p className="mt-1 text-sm text-gray-800">
									{selectedDocument.uploaded_by}
								</p>
							</div>

							<div>
								<p className="text-xs font-semibold text-gray-500">
									Created At
								</p>

								<p className="mt-1 text-sm text-gray-800">
									{selectedDocument.created_at}
								</p>
							</div>
						</div>

						<div className="mt-6 flex justify-end">
							<button
								type="button"
								onClick={closeDocumentMetadata}
								className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-700"
							>
								Close
							</button>
						</div>
					</div>
				</div>
			)}
		</section>
	);
}

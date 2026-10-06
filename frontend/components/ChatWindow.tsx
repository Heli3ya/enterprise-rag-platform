"use client";

import { useRef, useState } from "react";

type Message = {
    id: number;
    role: "user" | "assistant";
    content: string;
    isLoading?: boolean;
};

const API_BASE_URL =
    process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000/api";

export default function ChatWindow() {
    const [messages, setMessages] = useState<Message[]>([
        {
            id: 1,
            role: "assistant",
            content:
                "Hello! I am your Enterprise RAG Assistant. How can I help you?",
        },
    ]);

    const [input, setInput] = useState("");
    const [isLoading, setIsLoading] = useState(false);

    const conversationId = useRef(
        `conversation-${Date.now()}-${Math.random()
            .toString(36)
            .slice(2, 10)}`
    );

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

            const response = await fetch(
                `${API_BASE_URL}/chat/ask/`,
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        Authorization: `Bearer ${accessToken}`,
                    },
                    body: JSON.stringify({
                        question,
                        conversation_id: conversationId.current,
                    }),
                }
            );

            if (!response.ok) {
                const errorText = await response.text();

                throw new Error(
                    errorText || "Failed to get a response from the server."
                );
            }

            if (!response.body) {
                throw new Error("Streaming response is not available.");
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder("utf-8");

            let buffer = "";

            while (true) {
                const { value, done } = await reader.read();

                if (done) {
                    break;
                }

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
                            eventType = line
                                .slice("event:".length)
                                .trim();
                        }

                        if (line.startsWith("data:")) {
                            eventData += line
                                .slice("data:".length)
                                .trim();
                        }
                    }

                    if (!eventType || !eventData) {
                        continue;
                    }

                    if (eventType === "token") {
                        const data = JSON.parse(eventData);

                        setMessages((currentMessages) =>
                            currentMessages.map((message) =>
                                message.id === assistantMessageId
                                    ? {
                                          ...message,
                                          content:
                                              message.content +
                                              (data.content || ""),
                                          isLoading: false,
                                      }
                                    : message
                            )
                        );
                    }

                    if (eventType === "citations") {
                        console.log(
                            "Chat citations:",
                            JSON.parse(eventData)
                        );
                    }

                    if (eventType === "error") {
                        const data = JSON.parse(eventData);

                        throw new Error(
                            data.error ||
                                "An error occurred during the chat."
                        );
                    }

                    if (eventType === "done") {
                        setMessages((currentMessages) =>
                            currentMessages.map((message) =>
                                message.id === assistantMessageId
                                    ? {
                                          ...message,
                                          isLoading: false,
                                      }
                                    : message
                            )
                        );
                    }
                }
            }

            setMessages((currentMessages) =>
                currentMessages.map((message) =>
                    message.id === assistantMessageId
                        ? {
                              ...message,
                              isLoading: false,
                          }
                        : message
                )
            );

            setIsLoading(false);
        } catch (error) {
            const errorMessage =
                error instanceof Error
                    ? error.message
                    : "An unexpected error occurred.";

            setMessages((currentMessages) =>
                currentMessages.map((message) =>
                    message.id === assistantMessageId
                        ? {
                              ...message,
                              content: `Sorry, an error occurred: ${errorMessage}`,
                              isLoading: false,
                          }
                        : message
                )
            );

            setIsLoading(false);
        }
    };

    const handleKeyDown = (
        event: React.KeyboardEvent<HTMLTextAreaElement>
    ) => {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            handleSend();
        }
    };

    return (
        <section className="mt-8 overflow-hidden rounded-xl bg-white shadow-lg">
            <div className="border-b border-gray-200 px-6 py-4">
                <h2 className="text-lg font-semibold text-gray-800">
                    Chat Assistant
                </h2>

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
                                    {message.role === "user"
                                        ? "You"
                                        : "Assistant"}
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
        </section>
    );
}
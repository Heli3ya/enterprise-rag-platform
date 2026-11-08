"use client";

import { useEffect, useRef, useState } from "react";
import {
	API_BASE_URL,
	authorizedFetch,
	openAuthenticatedFile,
	readErrorMessage,
} from "../lib/api";
import {
	type ChunkDetail,
	type Citation,
	citationLabel,
	type DocumentPreview,
} from "../lib/citations";
import HighlightedText from "./HighlightedText";
import { useT } from "./PreferencesProvider";

type CitationPanelProps = {
	citation: Citation | null;
	/** The question behind this citation; used to highlight the match. */
	query?: string;
	onClose: () => void;
};

type Tab = "document" | "passage";

/**
 * Right-hand drawer that resolves a citation marker into the exact
 * passage that was retrieved, and shows where it sits in the original
 * document with the searched terms highlighted.
 */
export default function CitationPanel({
	citation,
	query = "",
	onClose,
}: CitationPanelProps) {
	const t = useT();
	const [detail, setDetail] = useState<ChunkDetail | null>(null);
	const [error, setError] = useState("");
	const [isLoading, setIsLoading] = useState(false);
	const [isOpeningFile, setIsOpeningFile] = useState(false);
	const [copied, setCopied] = useState(false);

	const [preview, setPreview] = useState<DocumentPreview | null>(null);
	const [previewError, setPreviewError] = useState("");
	const [isPreviewLoading, setIsPreviewLoading] = useState(false);
	const [tab, setTab] = useState<Tab>("document");

	const scrollRef = useRef<HTMLDivElement | null>(null);

	const chunkId = citation?.chunk_id ?? null;
	const documentId = citation?.document_id ?? null;

	// Reset everything when another citation is opened.
	useEffect(() => {
		if (chunkId === null) {
			setDetail(null);
			setError("");
			setCopied(false);
			setPreview(null);
			setPreviewError("");

			return;
		}

		let isCancelled = false;

		const loadChunk = async () => {
			setIsLoading(true);
			setError("");
			setDetail(null);
			setCopied(false);
			setPreview(null);
			setPreviewError("");
			setTab("document");

			try {
				const search = query ? `?q=${encodeURIComponent(query)}` : "";

				const response = await authorizedFetch(
					`${API_BASE_URL}/documents/chunks/${chunkId}/${search}`,
					{ method: "GET" },
				);

				if (!response.ok) {
					throw new Error(await readErrorMessage(response));
				}

				const data: ChunkDetail = await response.json();

				if (!isCancelled) {
					setDetail(data);
				}
			} catch (caughtError) {
				if (!isCancelled) {
					setError(
						caughtError instanceof Error
							? caughtError.message
							: t("Could not load this citation."),
					);
				}
			} finally {
				if (!isCancelled) {
					setIsLoading(false);
				}
			}
		};

		loadChunk();

		return () => {
			isCancelled = true;
		};
	}, [chunkId, query]);

	// Load the whole document the first time the tab is opened.
	useEffect(() => {
		if (tab !== "document" || documentId === null) {
			return;
		}

		if (preview || previewError) {
			return;
		}

		let isCancelled = false;

		const loadPreview = async () => {
			setIsPreviewLoading(true);
			setPreviewError("");

			try {
				const search = query ? `?q=${encodeURIComponent(query)}` : "";

				const response = await authorizedFetch(
					`${API_BASE_URL}/documents/${documentId}/preview/${search}`,
					{ method: "GET" },
				);

				if (!response.ok) {
					throw new Error(await readErrorMessage(response));
				}

				const data: DocumentPreview = await response.json();

				if (!isCancelled) {
					setPreview(data);
				}
			} catch (caughtError) {
				if (!isCancelled) {
					setPreviewError(
						caughtError instanceof Error
							? caughtError.message
							: t("Could not load the document."),
					);
				}
			} finally {
				if (!isCancelled) {
					setIsPreviewLoading(false);
				}
			}
		};

		loadPreview();

		return () => {
			isCancelled = true;
		};
	}, [tab, documentId, query, preview, previewError]);

	// Bring the first match into view once the document text is rendered.
	useEffect(() => {
		if (!preview || tab !== "document") {
			return;
		}

		const container = scrollRef.current;
		const mark = container?.querySelector("mark");

		if (!container || !mark) {
			return;
		}

		container.scrollTop = Math.max(
			0,
			(mark as HTMLElement).offsetTop - container.clientHeight / 3,
		);
	}, [preview, tab]);

	// Close on Escape so the drawer behaves like a dialog.
	useEffect(() => {
		if (!citation) {
			return;
		}

		const handleKeyDown = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				onClose();
			}
		};

		window.addEventListener("keydown", handleKeyDown);

		return () => window.removeEventListener("keydown", handleKeyDown);
	}, [citation, onClose]);

	if (!citation) {
		return null;
	}

	const handleOpenFile = async () => {
		const fileUrl = detail?.file_url ?? citation.file_url;

		if (!fileUrl) {
			return;
		}

		setIsOpeningFile(true);
		setError("");

		try {
			await openAuthenticatedFile(`${API_BASE_URL}${fileUrl}`);
		} catch (caughtError) {
			setError(
				caughtError instanceof Error
					? caughtError.message
					: t("Could not open the file."),
			);
		} finally {
			setIsOpeningFile(false);
		}
	};

	const handleCopy = async () => {
		const text = detail?.content ?? preview?.content;

		if (!text) {
			return;
		}

		try {
			await navigator.clipboard.writeText(text);
			setCopied(true);
			window.setTimeout(() => setCopied(false), 2000);
		} catch {
			setError(t("Copying is not available in this browser."));
		}
	};

	const title =
		detail?.document_title ??
		preview?.title ??
		citation.title ??
		citationLabel(citation);

	const matchedTerms = preview?.matched_terms ?? detail?.matched_terms ?? [];

	return (
		<div className="fixed inset-0 z-50 flex justify-end">
			<button
				type="button"
				aria-label={t("Close source panel")}
				onClick={onClose}
				className="absolute inset-0 cursor-default bg-black/40"
			/>

			<aside
				role="dialog"
				aria-modal="true"
				aria-label={t("Citation source")}
				className="relative flex h-full w-full max-w-lg flex-col bg-white shadow-2xl"
			>
				<header className="flex items-start justify-between gap-4 border-b border-gray-200 px-5 py-4">
					<div className="min-w-0">
						<p className="text-xs font-semibold uppercase tracking-wide text-blue-600">
							{t("Source")} [{citation.chunk_id}]
						</p>

						<h3 className="mt-1 truncate text-base font-semibold text-gray-800">
							{title}
						</h3>

						<p className="mt-1 text-xs text-gray-500">
							{citation.department}
							{citation.chunk_index !== undefined
								? ` · ${t("Chunk {index}", {
										index: citation.chunk_index + 1,
									})}`
								: ""}
						</p>
					</div>

					<button
						type="button"
						onClick={onClose}
						className="rounded-md px-2 py-1 text-gray-500 transition hover:bg-gray-100 hover:text-gray-800"
					>
						{t("Close")}
					</button>
				</header>

				<div className="flex gap-1 border-b border-gray-200 px-5 pt-2">
					<button
						type="button"
						onClick={() => setTab("document")}
						aria-pressed={tab === "document"}
						className={
							tab === "document"
								? "rounded-t-md border-b-2 border-blue-600 px-3 py-2 text-sm font-medium text-blue-700"
								: "rounded-t-md border-b-2 border-transparent px-3 py-2 text-sm text-gray-500 hover:text-gray-800"
						}
					>
						{t("In the document")}
					</button>

					<button
						type="button"
						onClick={() => setTab("passage")}
						aria-pressed={tab === "passage"}
						className={
							tab === "passage"
								? "rounded-t-md border-b-2 border-blue-600 px-3 py-2 text-sm font-medium text-blue-700"
								: "rounded-t-md border-b-2 border-transparent px-3 py-2 text-sm text-gray-500 hover:text-gray-800"
						}
					>
						{t("Cited passage")}
					</button>
				</div>

				<div
					ref={scrollRef}
					className="relative flex-1 overflow-y-auto px-5 py-4"
				>
					{isLoading && (
						<p className="text-sm text-gray-500">{t("Loading citation...")}</p>
					)}

					{error && (
						<p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
							{error}
						</p>
					)}

					{tab === "document" && (
						<>
							{isPreviewLoading && (
								<p className="text-sm text-gray-500">
									{t("Loading the document text...")}
								</p>
							)}

							{previewError && (
								<div className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
									<p>{previewError}</p>

									<button
										type="button"
										onClick={() => setTab("passage")}
										className="mt-2 text-xs font-semibold text-amber-900 underline"
									>
										{t("Show the cited passage instead")}
									</button>
								</div>
							)}

							{preview && (
								<>
									<p className="mb-2 text-[11px] text-gray-500">
										{matchedTerms.length > 0
											? `${t("Highlighted:")} ${matchedTerms.join(", ")}`
											: t(
													"No keyword match in this file — the answer came from a semantic match.",
												)}
									</p>

									<p className="whitespace-pre-wrap text-sm leading-6 text-gray-800">
										<HighlightedText
											text={preview.content}
											ranges={preview.highlights}
										/>
									</p>

									{preview.truncated && (
										<p className="mt-3 rounded-lg bg-gray-50 px-3 py-2 text-xs text-gray-500">
											This file is long; only the beginning is shown. Use “Open
											original file” for the complete document.
										</p>
									)}
								</>
							)}
						</>
					)}

					{tab === "passage" && (
						<>
							{!isLoading && !detail && !error && citation.snippet && (
								<>
									<p className="mb-2 text-[11px] text-gray-500">
										CITED PASSAGE
									</p>

									<p className="whitespace-pre-wrap rounded-lg bg-gray-50 p-3 text-sm leading-6 text-gray-800">
										{citation.snippet}
									</p>
								</>
							)}

							{detail && (
								<div className="space-y-4">
									<div>
										<p className="mb-2 text-[11px] text-gray-500">
											CITED PASSAGE
										</p>

										<p className="whitespace-pre-wrap rounded-lg bg-gray-50 p-3 text-sm leading-6 text-gray-800">
											<HighlightedText
												text={detail.content}
												ranges={detail.highlights}
											/>
										</p>

										{matchedTerms.length > 0 && (
											<p className="mt-2 text-[11px] text-gray-500">
												Highlighted:{" "}
												<span className="font-medium text-gray-700">
													{matchedTerms.join(", ")}
												</span>
											</p>
										)}
									</div>

									<dl className="grid grid-cols-2 gap-3 text-xs">
										<div>
											<dt className="font-semibold text-gray-500">
												{t("File")}
											</dt>
											<dd className="mt-1 break-all text-gray-800">
												{detail.filename}
											</dd>
										</div>

										<div>
											<dt className="font-semibold text-gray-500">
												{t("Type")}
											</dt>
											<dd className="mt-1 text-gray-800">{detail.file_type}</dd>
										</div>

										<div>
											<dt className="font-semibold text-gray-500">
												Department
											</dt>
											<dd className="mt-1 text-gray-800">
												{detail.department}
											</dd>
										</div>

										<div>
											<dt className="font-semibold text-gray-500">
												Uploaded by
											</dt>
											<dd className="mt-1 text-gray-800">
												{detail.uploaded_by}
											</dd>
										</div>
									</dl>
								</div>
							)}
						</>
					)}
				</div>

				<footer className="flex items-center justify-between gap-3 border-t border-gray-200 px-5 py-4">
					<button
						type="button"
						onClick={handleCopy}
						disabled={!detail && !preview}
						className="rounded-lg border border-gray-300 px-3 py-2 text-sm font-medium text-gray-700 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
					>
						{copied ? t("Copied") : t("Copy text")}
					</button>

					<button
						type="button"
						onClick={handleOpenFile}
						disabled={isOpeningFile}
						className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
					>
						{isOpeningFile ? t("Opening...") : t("Open original file")}
					</button>
				</footer>
			</aside>
		</div>
	);
}

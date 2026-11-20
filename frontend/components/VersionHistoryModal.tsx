"use client";

import { useEffect, useState } from "react";
import api from "@/lib/api";
import { formatDateTime, formatFileSize } from "@/lib/formatters";
import {
	normalizeVersionHistory,
	type VersionEntry,
	type VersionHistoryResponse,
} from "@/lib/versionHistory";
import { usePreferences, useT } from "./PreferencesProvider";

type HistoryTarget = {
	id: number;
	title?: string;
};

type VersionHistoryModalProps = {
	/** `null` means closed; the parent owns that state. */
	target: HistoryTarget | null;
	onClose: () => void;
};

function getErrorMessage(error: unknown): string {
	const err = error as {
		response?: { data?: { detail?: string; error?: string } };
		message?: string;
	};

	return (
		err.response?.data?.detail ||
		err.response?.data?.error ||
		err.message ||
		"An unexpected error occurred."
	);
}

export default function VersionHistoryModal({
	target,
	onClose,
}: VersionHistoryModalProps) {
	const t = useT();
	const { locale } = usePreferences();
	const [versions, setVersions] = useState<VersionEntry[]>([]);
	const [isLoading, setIsLoading] = useState(false);
	const [error, setError] = useState("");

	useEffect(() => {
		if (!target) {
			return;
		}

		let active = true;

		setIsLoading(true);
		setError("");
		setVersions([]);

		api
			.get<VersionHistoryResponse>(`/documents/${target.id}/versions/`)
			.then((response) => {
				if (active) {
					setVersions(normalizeVersionHistory(response.data));
				}
			})
			.catch((caught: unknown) => {
				if (active) {
					setError(getErrorMessage(caught));
				}
			})
			.finally(() => {
				if (active) {
					setIsLoading(false);
				}
			});

		return () => {
			active = false;
		};
	}, [target]);

	// Escape closes the dialog like any other modal surface in this app.
	useEffect(() => {
		if (!target) {
			return;
		}

		const onKeyDown = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				onClose();
			}
		};

		window.addEventListener("keydown", onKeyDown);

		return () => window.removeEventListener("keydown", onKeyDown);
	}, [target, onClose]);

	if (!target) {
		return null;
	}

	return (
		<div className="fixed inset-0 z-50 flex items-center justify-center p-4">
			<button
				type="button"
				aria-label={t("Close version history")}
				onClick={onClose}
				className="absolute inset-0 cursor-default bg-black/50"
			/>

			<section
				role="dialog"
				aria-modal="true"
				aria-label={t("Version history")}
				data-testid="version-history-dialog"
				className="relative flex max-h-[85vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl bg-white shadow-2xl"
			>
				<header className="flex items-start justify-between gap-4 border-b border-gray-200 px-5 py-4">
					<div className="min-w-0">
						<h3 className="text-base font-semibold text-gray-900">
							{t("Version history")}
						</h3>
						<p className="mt-1 truncate text-sm text-gray-500">
							{target.title || `#${target.id}`}
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

				<div className="flex-1 overflow-y-auto px-5 py-4">
					{isLoading ? (
						<p className="py-8 text-center text-sm text-gray-500">
							{t("Loading version history...")}
						</p>
					) : error ? (
						<p
							role="alert"
							className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
						>
							{error}
						</p>
					) : versions.length === 0 ? (
						<p className="py-8 text-center text-sm text-gray-500">
							{t("No versions found.")}
						</p>
					) : (
						<table className="w-full min-w-[480px] border-collapse text-start text-sm">
							<thead>
								<tr className="border-b border-gray-200 text-gray-600">
									<th scope="col" className="px-2 py-2 font-medium">
										{t("Version")}
									</th>
									<th scope="col" className="px-2 py-2 font-medium">
										{t("Status")}
									</th>
									<th scope="col" className="px-2 py-2 font-medium">
										{t("Uploaded")}
									</th>
									<th scope="col" className="px-2 py-2 font-medium">
										{t("Size")}
									</th>
								</tr>
							</thead>
							<tbody>
								{versions.map((version) => (
									<tr
										key={version.id}
										data-testid="version-history-row"
										className="border-b border-gray-100 last:border-0"
									>
										<td className="whitespace-nowrap px-2 py-3 font-medium text-gray-800">
											{t("v{version}", { version: String(version.version) })}
											{version.is_current && (
												<span
													data-testid="version-history-current"
													className="ms-2 inline-flex rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700"
												>
													{t("Current")}
												</span>
											)}
										</td>
										<td className="px-2 py-3 text-gray-600">
											<span
												className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${
													version.status?.toLowerCase() === "archived"
														? "bg-gray-200 text-gray-600"
														: "bg-green-100 text-green-700"
												}`}
											>
												{t(version.status || "Pending")}
											</span>
										</td>
										<td className="whitespace-nowrap px-2 py-3 text-gray-600">
											{formatDateTime(version.created_at, locale)}
										</td>
										<td className="whitespace-nowrap px-2 py-3 text-gray-600">
											{formatFileSize(version.file_size)}
										</td>
									</tr>
								))}
							</tbody>
						</table>
					)}
				</div>

				<footer className="flex justify-end border-t border-gray-200 px-5 py-3">
					<button
						type="button"
						onClick={onClose}
						className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
					>
						{t("Close")}
					</button>
				</footer>
			</section>
		</div>
	);
}

"use client";

import { useEffect, useRef, useState } from "react";
import {
	fetchNegativeFeedback,
	type NegativeFeedbackRow,
	type Paginated,
} from "../../lib/quality";
import { useT } from "../PreferencesProvider";

type DepartmentOption = {
	department_id: number;
	department_name: string;
};

type Props = {
	departments: DepartmentOption[];
};

const PAGE_SIZE = 10;

function formatDate(value: string): string {
	const date = new Date(value);

	if (Number.isNaN(date.getTime())) return "—";

	return new Intl.DateTimeFormat(undefined, {
		dateStyle: "medium",
		timeStyle: "short",
	}).format(date);
}

/**
 * Every answer that got a thumbs-down, newest first.
 *
 * This is the half of the dashboard that can be acted on: the KPI says
 * whether quality is slipping, this table says where. Filtering by
 * department and searching the free text are the two moves an admin
 * actually makes, so both are here instead of a bare list.
 *
 * The answer text is collapsed by default — a table of full answers is
 * unreadable — but it has to be present, because "the answer was wrong"
 * cannot be judged from the question alone.
 */
export default function NegativeFeedbackGrid({ departments }: Props) {
	const t = useT();

	const [rows, setRows] = useState<Paginated<NegativeFeedbackRow> | null>(null);
	const [page, setPage] = useState(1);
	const [departmentId, setDepartmentId] = useState<number | "">("");
	const [hasCommentOnly, setHasCommentOnly] = useState(false);
	const [searchInput, setSearchInput] = useState("");
	const [search, setSearch] = useState("");
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState("");

	// Debounce: one request per pause in typing, not one per keystroke.
	const debounceRef = useRef<number | null>(null);

	useEffect(() => {
		if (debounceRef.current !== null) {
			window.clearTimeout(debounceRef.current);
		}

		debounceRef.current = window.setTimeout(() => {
			setSearch(searchInput.trim());
			setPage(1);
		}, 350);

		return () => {
			if (debounceRef.current !== null) {
				window.clearTimeout(debounceRef.current);
			}
		};
	}, [searchInput]);

	useEffect(() => {
		let active = true;

		const load = async () => {
			setLoading(true);
			setError("");

			try {
				const payload = await fetchNegativeFeedback({
					page,
					pageSize: PAGE_SIZE,
					departmentId: departmentId === "" ? undefined : departmentId,
					search,
					hasComment: hasCommentOnly,
				});

				if (active) {
					setRows(payload);
				}
			} catch (err) {
				console.error("Failed to load negative feedback:", err);

				if (active) {
					setError(t("Could not load the feedback list. Please try again."));
				}
			} finally {
				if (active) {
					setLoading(false);
				}
			}
		};

		void load();

		return () => {
			active = false;
		};
	}, [page, departmentId, search, hasCommentOnly, t]);

	const total = rows?.count ?? 0;
	const firstRow = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
	const lastRow = Math.min(page * PAGE_SIZE, total);
	const canGoBack = Boolean(rows?.previous) && page > 1;
	const canGoForward = Boolean(rows?.next);

	return (
		<section
			data-testid="negative-feedback-grid"
			className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm"
		>
			<div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
				<div>
					<h2 className="text-lg font-semibold text-gray-800">
						{t("Answers rated thumbs down")}
					</h2>
					<p className="mt-1 text-sm text-gray-500">
						{t(
							"Read what went wrong, with the question, the answer and the user's comment",
						)}
					</p>
				</div>

				<span
					data-testid="negative-feedback-total"
					className="shrink-0 rounded-full bg-red-50 px-3 py-1 text-sm font-medium text-red-700"
				>
					{t("{count} in total", { count: total.toLocaleString() })}
				</span>
			</div>

			<div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center">
				<label className="flex-1">
					<span className="sr-only">{t("Search feedback")}</span>
					<input
						type="search"
						value={searchInput}
						onChange={(event) => setSearchInput(event.target.value)}
						placeholder={t("Search the question, the answer or the comment")}
						className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-800 placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
					/>
				</label>

				<label className="sm:w-56">
					<span className="sr-only">{t("Department")}</span>
					<select
						value={departmentId}
						onChange={(event) => {
							const value = event.target.value;
							setDepartmentId(value === "" ? "" : Number(value));
							setPage(1);
						}}
						className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-800 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
					>
						<option value="">{t("All departments")}</option>
						{departments.map((department) => (
							<option
								key={department.department_id}
								value={department.department_id}
							>
								{department.department_name}
							</option>
						))}
					</select>
				</label>

				<label className="flex items-center gap-2 text-sm text-gray-600">
					<input
						type="checkbox"
						checked={hasCommentOnly}
						onChange={(event) => {
							setHasCommentOnly(event.target.checked);
							setPage(1);
						}}
						className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
					/>
					{t("With a comment only")}
				</label>
			</div>

			{error ? (
				<p className="mt-4 text-sm text-red-600">{error}</p>
			) : loading && rows === null ? (
				<p className="mt-4 text-sm text-gray-500">
					{t("Loading dashboard...")}
				</p>
			) : total === 0 ? (
				<p
					data-testid="negative-feedback-empty"
					className="mt-6 text-sm text-gray-500"
				>
					{t(
						"No thumbs-down in this window. Either quality is fine or nobody is rating.",
					)}
				</p>
			) : (
				<>
					<div className="mt-4 overflow-x-auto">
						<table className="w-full min-w-[900px] text-start text-sm">
							<thead>
								<tr className="border-b border-gray-200 text-gray-500">
									<th className="px-3 py-3 text-start font-medium">
										{t("Date")}
									</th>
									<th className="px-3 py-3 text-start font-medium">
										{t("User")}
									</th>
									<th className="px-3 py-3 text-start font-medium">
										{t("Department")}
									</th>
									<th className="px-3 py-3 text-start font-medium">
										{t("Question")}
									</th>
									<th className="px-3 py-3 text-start font-medium">
										{t("User comment")}
									</th>
									<th className="px-3 py-3 text-start font-medium">
										{t("Answer")}
									</th>
								</tr>
							</thead>
							<tbody>
								{rows?.results.map((row) => (
									<tr
										key={row.id}
										data-testid="negative-feedback-row"
										className="border-b border-gray-100 align-top last:border-0"
									>
										<td className="whitespace-nowrap px-3 py-3 text-gray-500">
											{formatDate(row.created_at)}
										</td>
										<td className="whitespace-nowrap px-3 py-3 font-medium text-gray-800">
											{row.username}
										</td>
										<td className="whitespace-nowrap px-3 py-3 text-gray-600">
											{row.department_name || "—"}
										</td>
										<td className="max-w-xs whitespace-normal break-words px-3 py-3 text-gray-700">
											{row.question}
										</td>
										<td className="max-w-xs whitespace-normal break-words px-3 py-3 text-gray-700">
											{row.user_comment || (
												<span className="text-gray-400">{t("No comment")}</span>
											)}
										</td>
										<td className="max-w-sm whitespace-normal break-words px-3 py-3 text-gray-600">
											<details>
												<summary className="cursor-pointer text-blue-600">
													{t("Show the answer")}
												</summary>
												<p className="mt-2 text-gray-700">
													{row.answer_text || "—"}
												</p>
												<p className="mt-1 text-xs text-gray-500">
													{t("{count} citations", {
														count: row.citation_count,
													})}
												</p>
											</details>
										</td>
									</tr>
								))}
							</tbody>
						</table>
					</div>

					<div className="mt-4 flex flex-col items-center justify-between gap-3 sm:flex-row">
						<p className="text-sm text-gray-500">
							{t("Showing {from}–{to} of {total}", {
								from: firstRow,
								to: lastRow,
								total: total.toLocaleString(),
							})}
						</p>

						<div className="flex gap-2">
							<button
								type="button"
								onClick={() => setPage((current) => Math.max(1, current - 1))}
								disabled={!canGoBack}
								className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
							>
								{t("Previous")}
							</button>
							<button
								type="button"
								onClick={() => setPage((current) => current + 1)}
								disabled={!canGoForward}
								className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-50"
							>
								{t("Next")}
							</button>
						</div>
					</div>
				</>
			)}
		</section>
	);
}

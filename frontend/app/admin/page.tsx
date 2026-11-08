"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
	Bar,
	BarChart,
	CartesianGrid,
	Cell,
	Pie,
	PieChart,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import api from "../../lib/api";
import { useT } from "../../components/PreferencesProvider";

type DepartmentStat = {
	department_id: number;
	department_name: string;
	document_count: number;
	file_size_bytes: number;
	search_count: number;
};

type RecentSearch = {
	id: number;
	username: string;
	department_name: string | null;
	query_text: string;
	created_at: string;
};

type Analytics = {
	total_documents: number;
	total_file_size_bytes: number;
	total_searches: number;
	departments: DepartmentStat[];
	recent_searches: RecentSearch[];
};

const chartColors = ["#2563eb", "#0d9488", "#7c3aed", "#ea580c", "#db2777"];

function formatBytes(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;

	const units = ["KB", "MB", "GB", "TB"];
	let value = bytes / 1024;
	let unitIndex = 0;

	while (value >= 1024 && unitIndex < units.length - 1) {
		value /= 1024;
		unitIndex += 1;
	}

	return `${value.toFixed(1)} ${units[unitIndex]}`;
}

function formatDate(value: string): string {
	const date = new Date(value);

	if (Number.isNaN(date.getTime())) return "—";

	return new Intl.DateTimeFormat(undefined, {
		dateStyle: "medium",
		timeStyle: "short",
	}).format(date);
}

export default function AdminDashboardPage() {
	const router = useRouter();
	const t = useT();
	const [analytics, setAnalytics] = useState<Analytics | null>(null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState("");

	useEffect(() => {
		let active = true;

		const loadDashboard = async () => {
			try {
				const profileResponse = await api.get("/auth/me/");

				if (profileResponse.data.role !== "Admin") {
					router.replace("/");
					return;
				}

				const response = await api.get("/admin/analytics/");

				if (active) {
					setAnalytics(response.data as Analytics);
				}
			} catch (err) {
				console.error("Failed to load admin dashboard:", err);

				if (active) {
					setError(t("Could not load dashboard data. Please try again."));
				}
			} finally {
				if (active) {
					setLoading(false);
				}
			}
		};

		void loadDashboard();

		return () => {
			active = false;
		};
	}, [router]);

	if (loading) {
		return (
			<main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center bg-gray-50">
				<p className="text-gray-600">{t("Loading dashboard...")}</p>
			</main>
		);
	}

	if (error || !analytics) {
		return (
			<main className="min-h-[calc(100vh-3.5rem)] bg-gray-50 p-6">
				<div className="mx-auto max-w-6xl rounded-xl bg-white p-6 shadow-sm">
					<h1 className="text-xl font-bold text-gray-800">
						{t("Admin Dashboard")}
					</h1>
					<p className="mt-3 text-red-600">
						{error || t("No dashboard data is available.")}
					</p>
					<button
						type="button"
						onClick={() => window.location.reload()}
						className="mt-4 rounded-lg bg-blue-600 px-4 py-2 text-white hover:bg-blue-700"
					>
						{t("Retry")}
					</button>
				</div>
			</main>
		);
	}

	return (
		<main className="min-h-[calc(100vh-3.5rem)] bg-gray-50 p-4 sm:p-8">
			<div className="mx-auto max-w-7xl space-y-8">
				<header className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
					<div>
						<p className="text-sm font-medium text-blue-600">
							{t("Enterprise RAG Platform")}
						</p>
						<h1 className="mt-1 text-3xl font-bold text-gray-900">
							{t("Admin Dashboard")}
						</h1>
						<p className="mt-2 text-gray-500">
							{t("Document usage and search activity")}
						</p>
					</div>

					<button
						type="button"
						onClick={() => router.push("/")}
						className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100"
					>
						{t("Back to workspace")}
					</button>
				</header>

				<section className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
					<article className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
						<p className="text-sm text-gray-500">{t("Total documents")}</p>
						<p className="mt-3 text-3xl font-bold text-gray-900">
							{analytics.total_documents.toLocaleString()}
						</p>
					</article>

					<article className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
						<p className="text-sm text-gray-500">{t("Total file volume")}</p>
						<p className="mt-3 text-3xl font-bold text-gray-900">
							{formatBytes(analytics.total_file_size_bytes)}
						</p>
					</article>

					<article className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
						<p className="text-sm text-gray-500">{t("Total searches")}</p>
						<p className="mt-3 text-3xl font-bold text-gray-900">
							{analytics.total_searches.toLocaleString()}
						</p>
					</article>
				</section>

				<section className="grid grid-cols-1 gap-6 xl:grid-cols-2">
					<article className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
						<h2 className="text-lg font-semibold text-gray-800">
							{t("Documents by department")}
						</h2>
						<p className="mt-1 text-sm text-gray-500">
							{t("Number of uploaded documents in each department")}
						</p>

						<div className="mt-5 h-80 w-full">
							{analytics.departments.length > 0 ? (
								<ResponsiveContainer width="100%" height="100%">
									<BarChart
										data={analytics.departments}
										margin={{
											top: 10,
											right: 12,
											left: 0,
											bottom: 10,
										}}
									>
										<CartesianGrid strokeDasharray="3 3" vertical={false} />
										<XAxis dataKey="department_name" tick={{ fontSize: 12 }} />
										<YAxis allowDecimals={false} />
										<Tooltip />
										<Bar
											dataKey="document_count"
											name={t("Documents")}
											fill="#2563eb"
											radius={[5, 5, 0, 0]}
										/>
									</BarChart>
								</ResponsiveContainer>
							) : (
								<p className="pt-12 text-center text-gray-500">
									{t("No department data available.")}
								</p>
							)}
						</div>
					</article>

					<article className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
						<h2 className="text-lg font-semibold text-gray-800">
							{t("Searches by department")}
						</h2>
						<p className="mt-1 text-sm text-gray-500">
							{t("Share of recorded searches by department")}
						</p>

						<div className="mt-5 h-80 w-full">
							{analytics.departments.some((item) => item.search_count > 0) ? (
								<ResponsiveContainer width="100%" height="100%">
									<PieChart>
										<Pie
											data={analytics.departments.filter(
												(item) => item.search_count > 0,
											)}
											dataKey="search_count"
											nameKey="department_name"
											cx="50%"
											cy="50%"
											outerRadius={105}
											label={({ name, percent }) =>
												`${name}: ${((percent ?? 0) * 100).toFixed(0)}%`
											}
										>
											{analytics.departments
												.filter((item) => item.search_count > 0)
												.map((item, index) => (
													<Cell
														key={item.department_id}
														fill={chartColors[index % chartColors.length]}
													/>
												))}
										</Pie>
										<Tooltip />
									</PieChart>
								</ResponsiveContainer>
							) : (
								<p className="pt-12 text-center text-gray-500">
									{t("No recorded searches by department yet.")}
								</p>
							)}
						</div>
					</article>
				</section>

				<section className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
					<div className="flex flex-col justify-between gap-2 sm:flex-row sm:items-center">
						<h2 className="text-lg font-semibold text-gray-800">
							{t("Recent searches")}
						</h2>
						<span className="text-sm text-gray-500">
							{t("Latest {count} records", {
								count: analytics.recent_searches.length,
							})}
						</span>
					</div>

					{analytics.recent_searches.length > 0 ? (
						<div className="mt-4 overflow-x-auto">
							<table className="w-full min-w-[650px] text-start text-sm">
								<thead>
									<tr className="border-b border-gray-200 text-gray-500">
										<th className="px-3 py-3 font-medium">{t("User")}</th>
										<th className="px-3 py-3 font-medium">
											{t("Department")}
										</th>
										<th className="px-3 py-3 font-medium">
											{t("Search query")}
										</th>
										<th className="px-3 py-3 font-medium">{t("Date")}</th>
									</tr>
								</thead>
								<tbody>
									{analytics.recent_searches.map((item) => (
										<tr
											key={item.id}
											className="border-b border-gray-100 last:border-0"
										>
											<td className="px-3 py-3 font-medium text-gray-800">
												{item.username}
											</td>
											<td className="px-3 py-3 text-gray-600">
												{item.department_name || "—"}
											</td>
											<td className="max-w-sm whitespace-normal break-words px-3 py-3 text-gray-700">
												{item.query_text}
											</td>
											<td className="whitespace-nowrap px-3 py-3 text-gray-500">
												{formatDate(item.created_at)}
											</td>
										</tr>
									))}
								</tbody>
							</table>
						</div>
					) : (
						<p className="mt-4 text-sm text-gray-500">
							{t("No search history is available yet.")}
						</p>
					)}
				</section>
			</div>
		</main>
	);
}

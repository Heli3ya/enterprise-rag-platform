"use client";

import { useCallback } from "react";
import {
	Bar,
	CartesianGrid,
	ComposedChart,
	Legend,
	Line,
	ResponsiveContainer,
	Tooltip,
	XAxis,
	YAxis,
} from "recharts";
import {
	type DepartmentQuality,
	formatRate,
	QUALITY_RANGES,
	type QualityMetrics,
	type QualityRange,
	rateTone,
} from "../../lib/quality";
import { useT } from "../PreferencesProvider";

type Props = {
	metrics: QualityMetrics | null;
	range: QualityRange;
	onRangeChange: (range: QualityRange) => void;
	loading: boolean;
	error: string;
	onRetry: () => void;
};

const toneClasses: Record<string, string> = {
	neutral: "text-gray-900",
	good: "text-emerald-600",
	warn: "text-amber-600",
	bad: "text-red-600",
};

function formatBucket(value: string): string {
	const date = new Date(`${value}T00:00:00`);

	if (Number.isNaN(date.getTime())) return value;

	return new Intl.DateTimeFormat(undefined, {
		month: "short",
		day: "numeric",
	}).format(date);
}

function formatPercent(value: unknown): string {
	if (typeof value !== "number") return "—";

	return `${value.toFixed(1)}%`;
}

/**
 * The "where" half of the KPI.
 *
 * A tenant-wide 40% is not actionable on its own: it can mean one
 * department is failing badly or every department is slightly unhappy.
 * Sorting worst-first turns the panel into a queue, and departments
 * with no ratings sink to the bottom instead of pretending to be 0%.
 */
function DepartmentQualityList({ rows }: { rows: DepartmentQuality[] }) {
	const t = useT();

	const ordered = [...rows].sort((a, b) => {
		if (a.satisfaction_rate === null && b.satisfaction_rate === null) {
			return a.department_name.localeCompare(b.department_name);
		}

		if (a.satisfaction_rate === null) return 1;
		if (b.satisfaction_rate === null) return -1;

		return a.satisfaction_rate - b.satisfaction_rate;
	});

	return (
		<div className="mt-6 border-t border-gray-100 pt-5">
			<div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
				<h3 className="text-sm font-semibold text-gray-800">
					{t("Quality by department")}
				</h3>
				<p className="text-xs text-gray-500">
					{t("Worst first — where the wrong answers come from")}
				</p>
			</div>

			<ul
				data-testid="quality-by-department"
				className="mt-2 divide-y divide-gray-100"
			>
				{ordered.map((row) => (
					<li
						key={row.department_id}
						data-testid="quality-department-row"
						className="flex items-center justify-between gap-3 py-2"
					>
						<span className="truncate text-sm text-gray-700">
							{row.department_name}
						</span>

						<span className="flex shrink-0 items-center gap-3 text-xs text-gray-500">
							<span>{t("{count} ratings", { count: row.rated })}</span>
							<span className="text-red-600">
								{t("{count} negative", { count: row.negative })}
							</span>
							<span
								className={`min-w-12 text-right text-sm font-semibold tabular-nums ${
									toneClasses[rateTone(row.satisfaction_rate)]
								}`}
							>
								{formatRate(row.satisfaction_rate)}
							</span>
						</span>
					</li>
				))}
			</ul>
		</div>
	);
}

/**
 * Quality trend over the selected window.
 *
 * Two series share one plot because they answer the same question from
 * two sides: the bars say how much evidence there is, the line says how
 * good it was. A 100% week built on one rating and a 100% week built on
 * two hundred look identical on the line alone.
 *
 * `connectNulls={false}` is deliberate. Days with no ratings come back
 * as `null`, and drawing a line straight through them would invent a
 * reading that nobody gave.
 */
export default function QualityTrendChart({
	metrics,
	range,
	onRangeChange,
	loading,
	error,
	onRetry,
}: Props) {
	const t = useT();

	// Derived, not state: a rating count of zero is the only thing that
	// decides whether there is a line to draw.
	const hasData = Boolean(metrics && metrics.totals.rated > 0);

	const handleRange = useCallback(
		(next: QualityRange) => () => onRangeChange(next),
		[onRangeChange],
	);

	if (error) {
		return (
			<section
				data-testid="quality-trend"
				className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm"
			>
				<h2 className="text-lg font-semibold text-gray-800">
					{t("Answer quality trend")}
				</h2>
				<p className="mt-3 text-sm text-red-600">{error}</p>
				<button
					type="button"
					onClick={onRetry}
					className="mt-4 rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100"
				>
					{t("Retry")}
				</button>
			</section>
		);
	}

	return (
		<section
			data-testid="quality-trend"
			className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm"
		>
			<div className="flex flex-col justify-between gap-3 sm:flex-row sm:items-start">
				<div>
					<h2 className="text-lg font-semibold text-gray-800">
						{t("Answer quality trend")}
					</h2>
					<p className="mt-1 text-sm text-gray-500">
						{t(
							"Satisfaction rate per period, with the number of ratings behind it",
						)}
					</p>
				</div>

				<fieldset className="flex shrink-0 items-center gap-1 rounded-lg bg-gray-100 p-1">
					<legend className="sr-only">{t("Reporting window")}</legend>
					{QUALITY_RANGES.map((value) => (
						<button
							key={value}
							type="button"
							onClick={handleRange(value)}
							aria-pressed={range === value}
							className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
								range === value
									? "bg-white text-gray-900 shadow-sm"
									: "text-gray-600 hover:text-gray-900"
							}`}
						>
							{t("{count} days", { count: value })}
						</button>
					))}
				</fieldset>
			</div>

			<dl className="mt-5 grid grid-cols-2 gap-4 xl:grid-cols-4">
				<div className="rounded-lg border border-gray-100 bg-gray-50 p-4">
					<dt className="text-sm text-gray-500">{t("Satisfaction rate")}</dt>
					<dd
						data-testid="quality-satisfaction-rate"
						className={`mt-2 text-3xl font-bold ${
							toneClasses[rateTone(metrics?.totals.satisfaction_rate ?? null)]
						}`}
					>
						{loading && !metrics
							? "…"
							: formatRate(metrics?.totals.satisfaction_rate ?? null)}
					</dd>
					<p className="mt-1 text-xs text-gray-500">
						{t("Positive ratings ÷ ratings received")}
					</p>
				</div>

				<div className="rounded-lg border border-gray-100 bg-gray-50 p-4">
					<dt className="text-sm text-gray-500">{t("Ratings received")}</dt>
					<dd
						data-testid="quality-rated-count"
						className="mt-2 text-3xl font-bold text-gray-900"
					>
						{(metrics?.totals.rated ?? 0).toLocaleString()}
					</dd>
					<p className="mt-1 text-xs text-gray-500">
						{t("Thumbs up {positive} · thumbs down {negative}", {
							positive: metrics?.totals.positive ?? 0,
							negative: metrics?.totals.negative ?? 0,
						})}
					</p>
				</div>

				<div className="rounded-lg border border-gray-100 bg-gray-50 p-4">
					<dt className="text-sm text-gray-500">
						{t("Answers with a negative verdict")}
					</dt>
					<dd
						data-testid="quality-negative-count"
						className="mt-2 text-3xl font-bold text-red-600"
					>
						{(metrics?.totals.negative ?? 0).toLocaleString()}
					</dd>
					<p className="mt-1 text-xs text-gray-500">
						{t("{count} of them left a comment", {
							count: metrics?.totals.negative_with_comment ?? 0,
						})}
					</p>
				</div>

				<div className="rounded-lg border border-gray-100 bg-gray-50 p-4">
					<dt className="text-sm text-gray-500">{t("Rating coverage")}</dt>
					<dd
						data-testid="quality-response-rate"
						className="mt-2 text-3xl font-bold text-gray-900"
					>
						{formatRate(metrics?.totals.response_rate ?? null)}
					</dd>
					<p className="mt-1 text-xs text-gray-500">
						{t("Ratings ÷ answers delivered ({count})", {
							count: (metrics?.totals.answers ?? 0).toLocaleString(),
						})}
					</p>
				</div>
			</dl>

			<div className="mt-6 h-80 w-full" dir="ltr">
				{hasData ? (
					<ResponsiveContainer width="100%" height="100%">
						<ComposedChart
							data={metrics?.trend ?? []}
							margin={{ top: 10, right: 12, left: 0, bottom: 10 }}
						>
							<CartesianGrid strokeDasharray="3 3" vertical={false} />
							<XAxis
								dataKey="date"
								tickFormatter={formatBucket}
								minTickGap={24}
								tick={{ fontSize: 12 }}
							/>
							<YAxis
								yAxisId="volume"
								allowDecimals={false}
								tick={{ fontSize: 12 }}
							/>
							<YAxis
								yAxisId="rate"
								orientation="right"
								domain={[0, 100]}
								tickFormatter={(value: number) => `${value}%`}
								tick={{ fontSize: 12 }}
							/>
							<Tooltip
								labelFormatter={(label) => formatBucket(String(label))}
								formatter={(value, name) => {
									if (name === t("Satisfaction rate")) {
										return [formatPercent(value), name];
									}

									return [String(value ?? 0), name];
								}}
							/>
							<Legend wrapperStyle={{ fontSize: 12 }} />
							<Bar
								yAxisId="volume"
								dataKey="rated"
								name={t("Ratings received")}
								fill="#bfdbfe"
								radius={[4, 4, 0, 0]}
							/>
							<Line
								yAxisId="rate"
								type="monotone"
								dataKey="satisfaction_rate"
								name={t("Satisfaction rate")}
								stroke="#2563eb"
								strokeWidth={2}
								connectNulls={false}
								dot={{ r: 2 }}
							/>
						</ComposedChart>
					</ResponsiveContainer>
				) : (
					<p
						data-testid="quality-trend-empty"
						className="pt-16 text-center text-gray-500"
					>
						{loading
							? t("Loading dashboard...")
							: t(
									"No ratings in this window yet. The trend appears as soon as users rate an answer.",
								)}
					</p>
				)}
			</div>

			{hasData && (metrics?.by_department.length ?? 0) > 0 ? (
				<DepartmentQualityList rows={metrics?.by_department ?? []} />
			) : null}
		</section>
	);
}

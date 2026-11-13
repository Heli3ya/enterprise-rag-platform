/**
 * Typed access to the admin quality endpoints.
 *
 * `null` is load-bearing in these types: the backend returns `null`
 * instead of `0` whenever a rate has no denominator, so "nobody rated
 * anything" can be rendered differently from "everybody rated it bad".
 * Every formatter below has to handle it.
 */

import api from "./api";

export type QualityWindow = {
	days: number;
	date_from: string;
	date_to: string;
	granularity: "day" | "week";
};

export type QualityTotals = {
	answers: number;
	rated: number;
	positive: number;
	negative: number;
	satisfaction_rate: number | null;
	response_rate: number | null;
	positive_share_of_answers: number | null;
	negative_with_comment: number;
};

export type QualityTrendPoint = {
	date: string;
	rated: number;
	positive: number;
	negative: number;
	satisfaction_rate: number | null;
};

export type DepartmentQuality = {
	department_id: number;
	department_name: string;
	rated: number;
	positive: number;
	negative: number;
	satisfaction_rate: number | null;
};

export type QualityMetrics = {
	window: QualityWindow;
	totals: QualityTotals;
	trend: QualityTrendPoint[];
	by_department: DepartmentQuality[];
};

export type NegativeFeedbackRow = {
	id: number;
	answer_id: string;
	question: string;
	answer_text: string;
	user_comment: string;
	username: string;
	department_id: number | null;
	department_name: string | null;
	citation_count: number;
	created_at: string;
};

export type Paginated<T> = {
	count: number;
	next: string | null;
	previous: string | null;
	results: T[];
};

export const QUALITY_RANGES = [7, 30, 90] as const;

export type QualityRange = (typeof QUALITY_RANGES)[number];

export async function fetchQualityMetrics(
	days: number,
	departmentId?: number,
): Promise<QualityMetrics> {
	const response = await api.get("/admin/quality-metrics/", {
		params: {
			days,
			...(departmentId ? { department_id: departmentId } : {}),
		},
	});

	return response.data as QualityMetrics;
}

export type NegativeFeedbackQuery = {
	page?: number;
	pageSize?: number;
	departmentId?: number;
	search?: string;
	hasComment?: boolean;
};

export async function fetchNegativeFeedback(
	query: NegativeFeedbackQuery = {},
): Promise<Paginated<NegativeFeedbackRow>> {
	const response = await api.get("/admin/quality-feedback/", {
		params: {
			page: query.page ?? 1,
			page_size: query.pageSize ?? 20,
			...(query.departmentId ? { department_id: query.departmentId } : {}),
			...(query.search ? { search: query.search } : {}),
			...(query.hasComment ? { has_comment: "true" } : {}),
		},
	});

	return response.data as Paginated<NegativeFeedbackRow>;
}

/** "72.4%" — or an em dash when there is no denominator. */
export function formatRate(rate: number | null): string {
	if (rate === null || Number.isNaN(rate)) return "—";

	return `${rate.toFixed(1)}%`;
}

/**
 * Satisfaction tone, used for the KPI colour.
 *
 * Deliberately not a percentage-of-max gradient: the thresholds encode
 * a judgement about when a RAG assistant is trustworthy, and that
 * judgement belongs next to the number, not in a generic colour scale.
 */
export function rateTone(
	rate: number | null,
): "neutral" | "good" | "warn" | "bad" {
	if (rate === null) return "neutral";
	if (rate >= 80) return "good";
	if (rate >= 60) return "warn";

	return "bad";
}

import api from "./api";

/**
 * Readiness of the signed-in user's department.
 *
 * Mirrors `GET /api/departments/readiness/`. `document_count` excludes
 * the auto-generated onboarding guide, so a brand-new department is
 * `is_empty: true` while still having something to answer from.
 */
export type DepartmentReadiness = {
	department_id: number;
	department_name: string;
	document_count: number;
	has_searchable_content: boolean;
	is_empty: boolean;
	onboarding_document_id: number | null;
};

/**
 * Never throws.
 *
 * The dashboard works without this probe (it only decides whether to
 * show the empty state), so a failing or slow endpoint must not turn
 * the home page into an error screen. `null` simply hides the banner.
 */
export async function fetchDepartmentReadiness(): Promise<DepartmentReadiness | null> {
	try {
		const response = await api.get<DepartmentReadiness>(
			"/departments/readiness/",
		);

		return response.data;
	} catch {
		return null;
	}
}

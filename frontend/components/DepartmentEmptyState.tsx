"use client";

import { useCallback, useState } from "react";
import { focusChatInput, focusDocumentUploader } from "../lib/focusTargets";
import type { DepartmentReadiness } from "../lib/readiness";
import EmptyState from "./EmptyState";
import { useT } from "./PreferencesProvider";

/**
 * Cold-start banner for the dashboard.
 *
 * Rendered only while the department has no user-uploaded document. It
 * is deliberately *not* a blocking wall: the assistant can already
 * answer from the generated onboarding guide, so the secondary action
 * sends the user to the chat instead of hiding it.
 *
 * The banner is purely presentational; `page.tsx` owns the readiness
 * state so it can refresh it after an upload without a reload.
 */

type DepartmentEmptyStateProps = {
	readiness: DepartmentReadiness | null;
	onRefresh: () => Promise<void>;
};

export default function DepartmentEmptyState({
	readiness,
	onRefresh,
}: DepartmentEmptyStateProps) {
	const t = useT();

	const [isRefreshing, setIsRefreshing] = useState(false);

	const handleRefresh = useCallback(async () => {
		setIsRefreshing(true);

		try {
			await onRefresh();
		} finally {
			setIsRefreshing(false);
		}
	}, [onRefresh]);

	// Nothing to say while the probe is loading, or when the department
	// already has content.
	if (!readiness?.is_empty) {
		return null;
	}

	return (
		<div className="space-y-3">
			<EmptyState
				title={t("Your department has no documents yet")}
				description={t(
					"The assistant answers only from documents in your department. Add the first one to get real answers — until then it answers from the platform guide.",
				)}
				primaryAction={{
					label: t("Upload your first document"),
					onClick: focusDocumentUploader,
				}}
				secondaryAction={{
					label: t("Ask the assistant how to use the platform"),
					onClick: focusChatInput,
				}}
			/>

			<p className="px-1 text-xs text-gray-500">
				{t("Already uploaded a file? Indexing takes a few moments.")}{" "}
				<button
					type="button"
					onClick={() => void handleRefresh()}
					disabled={isRefreshing}
					className="font-medium text-blue-600 underline underline-offset-2 disabled:opacity-50"
				>
					{isRefreshing ? t("Refreshing...") : t("Refresh status")}
				</button>
			</p>
		</div>
	);
}

"use client";

import { useCallback, useEffect, useState } from "react";
import { useAuth } from "../components/AuthProvider";
import ChatWindow from "../components/ChatWindow";
import DepartmentEmptyState from "../components/DepartmentEmptyState";
import DocumentUploader from "../components/DocumentUploader";
import { useT } from "../components/PreferencesProvider";
import withAuth from "../components/withAuth";
import {
	type DepartmentReadiness,
	fetchDepartmentReadiness,
} from "../lib/readiness";

function Home() {
	const { user } = useAuth();
	const t = useT();

	// `null` means "unknown": either still loading, or the probe failed.
	// Both cases simply hide the cold-start banner.
	const [readiness, setReadiness] = useState<DepartmentReadiness | null>(null);

	const refreshReadiness = useCallback(async () => {
		setReadiness(await fetchDepartmentReadiness());
	}, []);

	useEffect(() => {
		void refreshReadiness();
	}, [refreshReadiness]);

	return (
		<main className="min-h-screen bg-gray-100 px-4 py-8 sm:px-8">
			<div className="mx-auto max-w-3xl space-y-8">
				<div className="rounded-xl bg-white p-6 shadow-lg sm:p-8">
					<h1 className="text-2xl font-bold text-gray-800">
						{t("Enterprise RAG Platform")}
					</h1>

					<p className="mt-3 text-gray-600">
						{t("Document Knowledge Base & Enterprise RAG")}
					</p>

					{user && (
						<div className="mt-6 rounded-lg bg-gray-100 p-4">
							<p className="text-sm text-gray-500">{t("Logged in as")}</p>

							<p className="mt-1 font-semibold text-gray-800">
								{user.username}
							</p>
						</div>
					)}

					{/* Cold start: shown only while the department has no
					    user-uploaded document. Disappears on its own after
					    the first successful upload. */}
					<div className="mt-8">
						<DepartmentEmptyState
							readiness={readiness}
							onRefresh={refreshReadiness}
						/>
					</div>
				</div>

				<DocumentUploader onUploaded={refreshReadiness} />

				<ChatWindow />
			</div>
		</main>
	);
}

export default withAuth(Home);

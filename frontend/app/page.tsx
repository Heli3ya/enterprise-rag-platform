"use client";

import { useAuth } from "../components/AuthProvider";
import ChatWindow from "../components/ChatWindow";
import DocumentUploader from "../components/DocumentUploader";
import { useT } from "../components/PreferencesProvider";
import withAuth from "../components/withAuth";

function Home() {
	const { user } = useAuth();
	const t = useT();

	return (
		<main className="min-h-screen bg-gray-100 px-4 py-8 sm:px-8">
			<div className="mx-auto max-w-3xl">
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

					<div className="mt-8">
						<h2 className="mb-4 text-lg font-semibold text-gray-800">
							{t("Upload Document")}
						</h2>

						<DocumentUploader />
					</div>

					<ChatWindow />
				</div>
			</div>
		</main>
	);
}

export default withAuth(Home);

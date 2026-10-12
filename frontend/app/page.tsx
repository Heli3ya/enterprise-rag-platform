"use client";

import { useAuth } from "../components/AuthProvider";
import ChatWindow from "../components/ChatWindow";
import DocumentUploader from "../components/DocumentUploader";
import withAuth from "../components/withAuth";

function Home() {
	const { user } = useAuth();

	return (
		<main className="min-h-screen bg-gray-100 p-8">
			<div className="mx-auto max-w-3xl">
				<div className="rounded-xl bg-white p-8 shadow-lg">
					<h1 className="text-2xl font-bold text-gray-800">
						Enterprise RAG Platform
					</h1>

					<p className="mt-3 text-gray-600">
						Document Knowledge Base & Enterprise RAG
					</p>

					{user && (
						<div className="mt-6 rounded-lg bg-gray-100 p-4">
							<p className="text-sm text-gray-500">Logged in as</p>

							<p className="mt-1 font-semibold text-gray-800">
								{user.username}
							</p>
						</div>
					)}

					<div className="mt-8">
						<h2 className="mb-4 text-lg font-semibold text-gray-800">
							Upload Document
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

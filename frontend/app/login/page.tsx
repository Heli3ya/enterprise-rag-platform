"use client";

import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useState } from "react";
import { useAuth } from "../../components/AuthProvider";
import api from "../../lib/api";

export default function LoginPage() {
	const router = useRouter();
	const { setUser } = useAuth();

	const [username, setUsername] = useState("");
	const [password, setPassword] = useState("");
	const [error, setError] = useState("");
	const [loading, setLoading] = useState(false);

	const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
		event.preventDefault();

		setError("");
		setLoading(true);

		try {
			const response = await api.post("/auth/login/", {
				username,
				password,
			});

			const { access, refresh } = response.data;

			localStorage.setItem("access_token", access);
			localStorage.setItem("refresh_token", refresh);

			setUser({
				username,
			});

			router.push("/");
		} catch (error) {
			console.error("Login failed:", error);
			setError("Username or password is incorrect.");
		} finally {
			setLoading(false);
		}
	};

	return (
		<main className="flex min-h-screen items-center justify-center bg-gray-100 px-4">
			<div className="w-full max-w-md rounded-xl bg-white p-8 shadow-lg">
				<h1 className="text-center text-2xl font-bold text-gray-800">Login</h1>

				<p className="mt-2 text-center text-gray-500">
					Sign in to Enterprise RAG Platform
				</p>

				<form onSubmit={handleSubmit} className="mt-6 space-y-5">
					<div>
						<label
							htmlFor="username"
							className="mb-2 block text-sm font-medium text-gray-700"
						>
							Username
						</label>

						<input
							id="username"
							type="text"
							value={username}
							onChange={(event) => setUsername(event.target.value)}
							required
							className="w-full rounded-lg border border-gray-300 px-4 py-2.5 outline-none focus:border-blue-500"
						/>
					</div>

					<div>
						<label
							htmlFor="password"
							className="mb-2 block text-sm font-medium text-gray-700"
						>
							Password
						</label>

						<input
							id="password"
							type="password"
							value={password}
							onChange={(event) => setPassword(event.target.value)}
							required
							className="w-full rounded-lg border border-gray-300 px-4 py-2.5 outline-none focus:border-blue-500"
						/>
					</div>

					{error && (
						<p className="text-sm text-red-600" role="alert">
							{error}
						</p>
					)}

					<button
						type="submit"
						disabled={loading}
						className="w-full rounded-lg bg-blue-600 px-5 py-2.5 font-medium text-white transition hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
					>
						{loading ? "Logging in..." : "Login"}
					</button>
				</form>
			</div>
		</main>
	);
}

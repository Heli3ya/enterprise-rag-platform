"use client";

import { isAxiosError } from "axios";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { useState } from "react";
import { useAuth } from "../../components/AuthProvider";
import { useT } from "../../components/PreferencesProvider";
import api from "../../lib/api";

type Translate = (text: string, vars?: Record<string, string | number>) => string;

/**
 * Turn an API/network failure into an accurate message.
 *
 * Reporting "wrong password" for a stopped backend was the most
 * misleading part of the login screen.
 */
function getLoginErrorMessage(error: unknown, t: Translate): string {
	if (isAxiosError(error)) {
		const status = error.response?.status;
		const detail = (error.response?.data as { detail?: string } | undefined)
			?.detail;

		if (status === 401) {
			return detail || t("Invalid username or password.");
		}

		if (status === 403) {
			return detail || t("Your account cannot access this organization.");
		}

		if (status === 400) {
			return detail || t("Please enter both username and password.");
		}

		if (!error.response) {
			return t(
				"Cannot reach the server. Make sure the backend is running, then try again.",
			);
		}

		if (status !== undefined && status >= 500) {
			return t(
				"The server is temporarily unavailable. Please try again in a moment.",
			);
		}

		return detail || `Login failed (HTTP ${status ?? "unknown"}).`;
	}

	return error instanceof Error
		? error.message
		: t("Login failed. Please try again.");
}

export default function LoginPage() {
	const router = useRouter();
	const t = useT();
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
			// Only this request determines whether the credentials are valid.
			const loginResponse = await api.post("/auth/login/", {
				username: username.trim(),
				password,
			});

			const accessToken = loginResponse.data?.access;
			const refreshToken = loginResponse.data?.refresh;

			if (!accessToken || !refreshToken) {
				throw new Error(
					t("The login response did not contain valid access and refresh tokens."),
				);
			}

			localStorage.setItem("access_token", accessToken);
			localStorage.setItem("refresh_token", refreshToken);

			try {
				// Profile errors must not be reported as incorrect credentials.
				const profileResponse = await api.get("/auth/me/");
				const profile = profileResponse.data;

				if (profile.role !== "Admin" && profile.role !== "Member") {
					throw new Error(t("The user role returned by the server is invalid."));
				}

				localStorage.setItem("user", JSON.stringify(profile));
				setUser(profile);

				router.replace(profile.role === "Admin" ? "/admin" : "/");
			} catch (profileError) {
				console.error("Profile loading failed after login:", profileError);
				setError(
					t("Login succeeded, but loading your profile failed. Please try again."),
				);
			}
		} catch (loginError) {
			console.error("Authentication request failed:", loginError);

			localStorage.removeItem("access_token");
			localStorage.removeItem("refresh_token");
			localStorage.removeItem("user");

			setError(getLoginErrorMessage(loginError, t));
		} finally {
			setLoading(false);
		}
	};

	return (
		<main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center bg-gray-100 px-4">
			<div className="w-full max-w-md rounded-xl bg-white p-8 shadow-lg">
				<h1 className="text-center text-2xl font-bold text-gray-800">
					{t("Login")}
				</h1>

				<p className="mt-2 text-center text-gray-500">
					{t("Sign in to Enterprise RAG Platform")}
				</p>

				<form onSubmit={handleSubmit} className="mt-6 space-y-5">
					<div>
						<label
							htmlFor="username"
							className="mb-2 block text-sm font-medium text-gray-700"
						>
							{t("Username")}
						</label>
						<input
							id="username"
							type="text"
							autoComplete="username"
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
							{t("Password")}
						</label>
						<input
							id="password"
							type="password"
							autoComplete="current-password"
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
						{loading ? t("Logging in...") : t("Login")}
					</button>
				</form>
			</div>
		</main>
	);
}

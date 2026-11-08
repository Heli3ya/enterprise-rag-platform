"use client";

import { isAxiosError } from "axios";
import { useRouter } from "next/navigation";
import type { ComponentType } from "react";
import { useCallback, useEffect, useState } from "react";
import api from "../lib/api";
import { useAuth } from "./AuthProvider";
import { useT } from "./PreferencesProvider";

export default function withAuth<P extends object>(
	Component: ComponentType<P>,
) {
	return function ProtectedComponent(props: P) {
		const router = useRouter();
		const t = useT();
		const { setUser, clearUser } = useAuth();
		const [isChecking, setIsChecking] = useState(true);
		const [checkError, setCheckError] = useState("");

		const checkAuthentication = useCallback(
			async (isActive: () => boolean) => {
				const accessToken = localStorage.getItem("access_token");

				if (!accessToken) {
					router.replace("/login");
					return;
				}

				try {
					const response = await api.get("/auth/me/");

					if (!isActive()) {
						return;
					}

					setUser(response.data);
					setCheckError("");
					setIsChecking(false);
				} catch (error) {
					if (!isActive()) {
						return;
					}

					const status = isAxiosError(error)
						? error.response?.status
						: undefined;

					// Only an authentication/authorization failure means the
					// session is really gone. A temporary network problem must
					// not silently log the user out.
					if (status === 401 || status === 403) {
						localStorage.removeItem("access_token");
						localStorage.removeItem("refresh_token");
						clearUser();
						router.replace("/login");
						return;
					}

					// Store a code, not a sentence: the message is translated
					// at render time so switching language re-renders it
					// without repeating the auth request.
					setCheckError(
						status !== undefined && status >= 500 ? "server" : "network",
					);
					setIsChecking(false);
				}
			},
			[router, setUser, clearUser],
		);

		useEffect(() => {
			let active = true;

			void checkAuthentication(() => active);

			return () => {
				active = false;
			};
		}, [checkAuthentication]);

		const retry = () => {
			setIsChecking(true);
			setCheckError("");
			void checkAuthentication(() => true);
		};

		if (isChecking) {
			return (
				<main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center">
					<p className="text-gray-600">{t("Checking authentication...")}</p>
				</main>
			);
		}

		if (checkError) {
			return (
				<main className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4">
					<div className="w-full max-w-md rounded-xl bg-white p-8 text-center shadow-lg">
						<h1 className="text-lg font-semibold text-gray-800">
							{t("Connection problem")}
						</h1>

						<p className="mt-3 text-sm text-gray-600">
							{checkError === "server"
								? t("The server is temporarily unavailable. Please try again.")
								: t(
										"Cannot reach the server. Check that the backend is running and try again.",
									)}
						</p>

						<button
							type="button"
							onClick={retry}
							className="mt-6 rounded-lg bg-blue-600 px-5 py-2.5 font-medium text-white transition hover:bg-blue-700"
						>
							{t("Try again")}
						</button>
					</div>
				</main>
			);
		}

		return <Component {...props} />;
	};
}

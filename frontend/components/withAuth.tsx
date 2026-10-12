"use client";

import { useRouter } from "next/navigation";
import type { ComponentType } from "react";
import { useEffect, useState } from "react";
import api from "../lib/api";
import { useAuth } from "./AuthProvider";

export default function withAuth<P extends object>(
	Component: ComponentType<P>,
) {
	return function ProtectedComponent(props: P) {
		const router = useRouter();
		const { setUser, clearUser } = useAuth();
		const [isChecking, setIsChecking] = useState(true);

		useEffect(() => {
			let active = true;

			const checkAuthentication = async () => {
				const accessToken = localStorage.getItem("access_token");

				if (!accessToken) {
					router.replace("/login");
					return;
				}

				try {
					const response = await api.get("/auth/me/");

					if (active) {
						setUser(response.data);
						setIsChecking(false);
					}
				} catch (error) {
					console.error("Authentication check failed:", error);

					if (active) {
						localStorage.removeItem("access_token");
						localStorage.removeItem("refresh_token");
						clearUser();
						router.replace("/login");
					}
				}
			};

			void checkAuthentication();

			return () => {
				active = false;
			};
		}, [router, setUser, clearUser]);

		if (isChecking) {
			return (
				<main className="flex min-h-screen items-center justify-center">
					<p className="text-gray-600">Checking authentication...</p>
				</main>
			);
		}

		return <Component {...props} />;
	};
}

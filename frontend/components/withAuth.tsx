"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import api from "../lib/api";

export default function withAuth<P extends object>(
	Component: React.ComponentType<P>,
) {
	return function ProtectedComponent(props: P) {
		const router = useRouter();
		const [isChecking, setIsChecking] = useState(true);

		useEffect(() => {
			const checkAuthentication = async () => {
				const accessToken = localStorage.getItem("access_token");

				if (!accessToken) {
					router.replace("/login");
					return;
				}

				try {
					await api.get("/departments/");
					setIsChecking(false);
				} catch (error) {
					console.error("Authentication check failed:", error);

					localStorage.removeItem("access_token");
					localStorage.removeItem("refresh_token");
					localStorage.removeItem("user");

					router.replace("/login");
				}
			};

			checkAuthentication();
		}, [router]);

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

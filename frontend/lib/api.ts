import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";

const api = axios.create({
	baseURL: process.env.NEXT_PUBLIC_API_BASE_URL,
	headers: {
		"Content-Type": "application/json",
	},
});

let refreshPromise: Promise<string | null> | null = null;

function isTokenExpiringSoon(token: string): boolean {
	try {
		const payload = JSON.parse(atob(token.split(".")[1]));
		const currentTime = Math.floor(Date.now() / 1000);

		return payload.exp - currentTime <= 60;
	} catch {
		return true;
	}
}

async function refreshAccessToken(): Promise<string | null> {
	if (typeof window === "undefined") {
		return null;
	}

	const refreshToken = localStorage.getItem("refresh_token");

	if (!refreshToken) {
		return null;
	}

	if (!refreshPromise) {
		refreshPromise = api
			.post("/auth/refresh/", {
				refresh: refreshToken,
			})
			.then((response) => {
				const newAccessToken = response.data.access;

				localStorage.setItem("access_token", newAccessToken);

				return newAccessToken;
			})
			.catch((error) => {
				console.error("Token refresh failed:", error);

				localStorage.removeItem("access_token");
				localStorage.removeItem("refresh_token");

				return null;
			})
			.finally(() => {
				refreshPromise = null;
			});
	}

	return refreshPromise;
}

api.interceptors.request.use(
	async (config: InternalAxiosRequestConfig) => {
		if (typeof window === "undefined") {
			return config;
		}

		const isRefreshRequest = config.url === "/auth/refresh/";

		if (isRefreshRequest) {
			return config;
		}

		let accessToken = localStorage.getItem("access_token");

		if (accessToken && isTokenExpiringSoon(accessToken)) {
			accessToken = await refreshAccessToken();
		}

		if (accessToken) {
			config.headers.Authorization = `Bearer ${accessToken}`;
		}

		return config;
	},
	(error) => Promise.reject(error),
);

api.interceptors.response.use(
	(response) => response,
	async (error: AxiosError) => {
		if (typeof window === "undefined") {
			return Promise.reject(error);
		}

		const originalRequest = error.config;

		if (
			error.response?.status !== 401 ||
			!originalRequest ||
			originalRequest.url === "/auth/refresh/" ||
			originalRequest.url === "/auth/login/"
		) {
			return Promise.reject(error);
		}

		const newAccessToken = await refreshAccessToken();

		if (!newAccessToken) {
			localStorage.removeItem("access_token");
			localStorage.removeItem("refresh_token");

			window.location.href = "/login";

			return Promise.reject(error);
		}

		originalRequest.headers.Authorization = `Bearer ${newAccessToken}`;

		return api(originalRequest);
	},
);

export default api;

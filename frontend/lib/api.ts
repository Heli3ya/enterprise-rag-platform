import axios, { type AxiosError, type InternalAxiosRequestConfig } from "axios";

export const API_BASE_URL =
	process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000/api";

const api = axios.create({
	baseURL: process.env.NEXT_PUBLIC_API_BASE_URL,
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
			.catch((error: unknown) => {
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

/**
 * Return a usable access token, refreshing it when it is about to expire.
 *
 * Streaming requests (chat) cannot go through the axios interceptors, so
 * they use this helper instead.
 */
export async function getValidAccessToken(): Promise<string | null> {
	if (typeof window === "undefined") {
		return null;
	}

	const accessToken = localStorage.getItem("access_token");

	if (accessToken && !isTokenExpiringSoon(accessToken)) {
		return accessToken;
	}

	const refreshedToken = await refreshAccessToken();

	if (refreshedToken) {
		return refreshedToken;
	}

	// If refreshing failed because the API is temporarily unreachable,
	// a still valid token can keep the current request working.
	if (accessToken && !isTokenExpiringSoon(accessToken)) {
		return accessToken;
	}

	return null;
}

export { refreshAccessToken };

/**
 * Extract a human readable message from a failed API response.
 */
export async function readErrorMessage(response: Response): Promise<string> {
	try {
		const payload = await response.json();

		return (
			payload?.detail ||
			payload?.error ||
			`Request failed with status ${response.status}.`
		);
	} catch {
		return `Request failed with status ${response.status}.`;
	}
}

/**
 * Fetch with a valid access token and a single retry after refreshing.
 *
 * Streaming requests (chat, SSE) and binary downloads (files) cannot
 * go through the axios interceptors, so they share this helper.
 */
export async function authorizedFetch(
	input: string,
	init: RequestInit = {},
): Promise<Response> {
	const accessToken = await getValidAccessToken();

	if (!accessToken) {
		throw new Error("Your session has expired. Please sign in again.");
	}

	let response = await fetch(input, {
		...init,
		headers: {
			...init.headers,
			Authorization: `Bearer ${accessToken}`,
		},
	});

	if (response.status === 401) {
		const refreshedToken = await refreshAccessToken();

		if (!refreshedToken) {
			throw new Error("Your session has expired. Please sign in again.");
		}

		response = await fetch(input, {
			...init,
			headers: {
				...init.headers,
				Authorization: `Bearer ${refreshedToken}`,
			},
		});
	}

	return response;
}

/**
 * Open a protected file in a new tab.
 *
 * The file endpoint requires an Authorization header, which a plain
 * link cannot send, so the bytes are fetched first and handed to the
 * browser as an object URL. Falls back to a download when the browser
 * blocks the popup.
 */
export async function openAuthenticatedFile(url: string): Promise<void> {
	const response = await authorizedFetch(url, { method: "GET" });

	if (!response.ok) {
		throw new Error(await readErrorMessage(response));
	}

	const blob = await response.blob();
	const objectUrl = URL.createObjectURL(blob);

	const openedWindow = window.open(objectUrl, "_blank");

	if (!openedWindow) {
		const link = document.createElement("a");

		link.href = objectUrl;
		link.download =
			url.split("/").filter(Boolean).slice(-2, -1)[0] || "document";
		document.body.appendChild(link);
		link.click();
		link.remove();
	}

	// Keep the object alive long enough for the new tab to load it.
	window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60_000);
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
	(error: unknown) => Promise.reject(error),
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

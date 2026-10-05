import axios from "axios";

const api = axios.create({
	baseURL: process.env.NEXT_PUBLIC_API_BASE_URL,
	headers: {
		"Content-Type": "application/json",
	},
});

api.interceptors.request.use(
	(config) => {
		if (typeof window !== "undefined") {
			const accessToken = localStorage.getItem("access_token");

			if (accessToken) {
				config.headers.Authorization = `Bearer ${accessToken}`;
			}
		}

		return config;
	},
	(error) => {
		return Promise.reject(error);
	},
);

export default api;

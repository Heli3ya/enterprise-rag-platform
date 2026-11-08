import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "../components/AuthProvider";
import HeaderBar from "../components/HeaderBar";
import { PreferencesProvider } from "../components/PreferencesProvider";

export const metadata: Metadata = {
	title: "Enterprise RAG Platform",
	description: "Document Knowledge Base & Enterprise RAG",
};

/**
 * Applies the stored language and theme before the first paint.
 *
 * Without this the page would render light/LTR and then jump to dark/RTL
 * once React hydrates, which looks like a flicker on every navigation.
 */
const bootstrapPreferences = `
(function () {
	try {
		var root = document.documentElement;
		var theme = localStorage.getItem("app_theme");
		var dark = theme === "dark" ||
			(!theme && window.matchMedia("(prefers-color-scheme: dark)").matches);
		if (dark) {
			root.classList.add("dark");
			root.style.colorScheme = "dark";
		}
		var locale = localStorage.getItem("app_locale") || "en";
		root.lang = locale;
		root.dir = locale === "fa" ? "rtl" : "ltr";
	} catch (error) {
		/* Storage can be blocked; the defaults are fine. */
	}
})();
`;

export default function RootLayout({
	children,
}: Readonly<{
	children: React.ReactNode;
}>) {
	return (
		<html lang="en" suppressHydrationWarning>
			<body>
				<script
					// biome-ignore lint/security/noDangerouslySetInnerHtml: static, no user input
					dangerouslySetInnerHTML={{ __html: bootstrapPreferences }}
				/>
				<PreferencesProvider>
					<AuthProvider>
						<HeaderBar />
						{children}
					</AuthProvider>
				</PreferencesProvider>
			</body>
		</html>
	);
}

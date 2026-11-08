"use client";

import type { Locale } from "../lib/i18n";
import { LOCALES } from "../lib/i18n";
import { usePreferences } from "./PreferencesProvider";

function SunIcon() {
	return (
		<svg
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			strokeWidth="1.8"
			strokeLinecap="round"
			className="h-[18px] w-[18px]"
			aria-hidden="true"
		>
			<circle cx="12" cy="12" r="4" />
			<path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
		</svg>
	);
}

function MoonIcon() {
	return (
		<svg
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			strokeWidth="1.8"
			strokeLinecap="round"
			strokeLinejoin="round"
			className="h-[18px] w-[18px]"
			aria-hidden="true"
		>
			<path d="M21 12.8A8.5 8.5 0 1 1 11.2 3a6.6 6.6 0 0 0 9.8 9.8Z" />
		</svg>
	);
}

export default function HeaderBar() {
	const { locale, theme, setLocale, toggleTheme, t } = usePreferences();

	return (
		<header className="sticky top-0 z-40 border-b border-gray-200 bg-white/85 backdrop-blur-md">
			<div className="mx-auto flex h-14 w-full max-w-5xl items-center justify-between gap-3 px-4 sm:px-6">
				<div className="flex min-w-0 items-center gap-2.5">
					<span
						className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-600 text-sm font-bold text-white shadow-sm"
						aria-hidden="true"
					>
						R
					</span>

					<span className="truncate text-sm font-semibold text-gray-800">
						{t("Enterprise RAG Platform")}
					</span>
				</div>

				<div className="flex shrink-0 items-center gap-2">
					<div
						className="flex items-center gap-0.5 rounded-lg border border-gray-200 bg-gray-50 p-0.5"
						role="group"
						aria-label={t("Language and theme")}
					>
						{LOCALES.map((item) => {
							const isActive = locale === item.value;

							return (
								<button
									key={item.value}
									type="button"
									onClick={() => setLocale(item.value as Locale)}
									aria-pressed={isActive}
									title={
										item.value === "en"
											? t("Switch to English")
											: t("Switch to Persian")
									}
									className={
										isActive
											? "rounded-md bg-white px-2.5 py-1 text-xs font-semibold text-blue-700 shadow-sm transition"
											: "rounded-md px-2.5 py-1 text-xs font-semibold text-gray-500 transition hover:text-gray-800"
									}
								>
									{item.short}
								</button>
							);
						})}
					</div>

					<button
						type="button"
						onClick={toggleTheme}
						aria-pressed={theme === "dark"}
						aria-label={
							theme === "dark"
								? t("Switch to light mode")
								: t("Switch to dark mode")
						}
						title={
							theme === "dark"
								? t("Switch to light mode")
								: t("Switch to dark mode")
						}
						className="flex h-8 w-8 items-center justify-center rounded-lg border border-gray-200 bg-gray-50 text-gray-600 transition hover:bg-gray-100 hover:text-gray-900"
					>
						{theme === "dark" ? <SunIcon /> : <MoonIcon />}
					</button>
				</div>
			</div>
		</header>
	);
}

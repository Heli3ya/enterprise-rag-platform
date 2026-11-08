"use client";

import {
	createContext,
	type ReactNode,
	useCallback,
	useContext,
	useEffect,
	useMemo,
	useState,
} from "react";
import {
	DEFAULT_LOCALE,
	type Locale,
	LOCALE_STORAGE_KEY,
	localeDirection,
	translate,
} from "../lib/i18n";

export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "app_theme";

type Preferences = {
	locale: Locale;
	theme: Theme;
	dir: "ltr" | "rtl";
	setLocale: (locale: Locale) => void;
	toggleLocale: () => void;
	setTheme: (theme: Theme) => void;
	toggleTheme: () => void;
	t: (text: string, vars?: Record<string, string | number>) => string;
};

const PreferencesContext = createContext<Preferences | null>(null);

function readStoredLocale(): Locale {
	if (typeof window === "undefined") {
		return DEFAULT_LOCALE;
	}

	try {
		const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY);
		return stored === "fa" || stored === "en" ? stored : DEFAULT_LOCALE;
	} catch {
		return DEFAULT_LOCALE;
	}
}

function readStoredTheme(): Theme {
	if (typeof window === "undefined") {
		return "light";
	}

	try {
		const stored = window.localStorage.getItem(THEME_STORAGE_KEY);

		if (stored === "dark" || stored === "light") {
			return stored;
		}

		return window.matchMedia("(prefers-color-scheme: dark)").matches
			? "dark"
			: "light";
	} catch {
		return "light";
	}
}

function applyDocumentPreferences(locale: Locale, theme: Theme) {
	const root = document.documentElement;

	root.lang = locale;
	root.dir = localeDirection(locale);
	root.classList.toggle("dark", theme === "dark");
	root.style.colorScheme = theme;
}

export function PreferencesProvider({ children }: { children: ReactNode }) {
	// Start from the SSR defaults and hydrate in an effect: the inline script
	// in the root layout has already painted the correct theme, so there is
	// no flash and no hydration mismatch.
	const [locale, setLocaleState] = useState<Locale>(DEFAULT_LOCALE);
	const [theme, setThemeState] = useState<Theme>("light");

	useEffect(() => {
		const storedLocale = readStoredLocale();
		const storedTheme = readStoredTheme();

		setLocaleState(storedLocale);
		setThemeState(storedTheme);
		applyDocumentPreferences(storedLocale, storedTheme);
	}, []);

	const setLocale = useCallback((next: Locale) => {
		setLocaleState(next);

		// Only touch the locale attributes: the theme class is owned by
		// `setTheme`, so the two preferences never overwrite each other.
		document.documentElement.lang = next;
		document.documentElement.dir = localeDirection(next);

		try {
			window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
		} catch {
			// Private mode: the preference simply does not persist.
		}
	}, []);

	const setTheme = useCallback((next: Theme) => {
		setThemeState(next);
		document.documentElement.classList.toggle("dark", next === "dark");
		document.documentElement.style.colorScheme = next;

		try {
			window.localStorage.setItem(THEME_STORAGE_KEY, next);
		} catch {
			// Private mode: the preference simply does not persist.
		}
	}, []);

	const toggleLocale = useCallback(() => {
		setLocale(locale === "fa" ? "en" : "fa");
	}, [locale, setLocale]);

	const toggleTheme = useCallback(() => {
		setTheme(theme === "dark" ? "light" : "dark");
	}, [theme, setTheme]);

	const t = useCallback(
		(text: string, vars?: Record<string, string | number>) =>
			translate(locale, text, vars),
		[locale],
	);

	const value = useMemo<Preferences>(
		() => ({
			locale,
			theme,
			dir: localeDirection(locale),
			setLocale,
			toggleLocale,
			setTheme,
			toggleTheme,
			t,
		}),
		[locale, theme, setLocale, toggleLocale, setTheme, toggleTheme, t],
	);

	return (
		<PreferencesContext.Provider value={value}>
			{children}
		</PreferencesContext.Provider>
	);
}

export function usePreferences(): Preferences {
	const context = useContext(PreferencesContext);

	if (!context) {
		throw new Error("usePreferences must be used inside PreferencesProvider");
	}

	return context;
}

/** Shorthand for components that only need the translator. */
export function useT() {
	return usePreferences().t;
}

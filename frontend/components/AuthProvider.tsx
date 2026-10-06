"use client";

import { createContext, useContext, useEffect, useState } from "react";

type User = {
	username: string;
};

type AuthContextType = {
	user: User | null;
	setUser: (user: User) => void;
	clearUser: () => void;
};

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
	const [user, setUserState] = useState<User | null>(null);

	useEffect(() => {
		const storedUser = localStorage.getItem("user");

		if (storedUser) {
			setUserState(JSON.parse(storedUser));
		}
	}, []);

	const setUser = (newUser: User) => {
		setUserState(newUser);
		localStorage.setItem("user", JSON.stringify(newUser));
	};

	const clearUser = () => {
		setUserState(null);
		localStorage.removeItem("user");
	};

	return (
		<AuthContext.Provider value={{ user, setUser, clearUser }}>
			{children}
		</AuthContext.Provider>
	);
}

export function useAuth() {
	const context = useContext(AuthContext);

	if (!context) {
		throw new Error("useAuth must be used inside AuthProvider");
	}

	return context;
}

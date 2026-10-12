"use client";
import {
	createContext,
	type ReactNode,
	useCallback,
	useContext,
	useEffect,
	useState,
} from "react";
export type User = {
	id?: number;
	username: string;
	role?: "Admin" | "Member";
	department_id?: number | null;
	department_name?: string | null;
};

type AuthContextType = {
	user: User | null;
	setUser: (user: User) => void;
	clearUser: () => void;
};

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
	const [user, setUserState] = useState<User | null>(null);

	useEffect(() => {
		try {
			const storedUser = localStorage.getItem("user");

			if (storedUser) {
				setUserState(JSON.parse(storedUser) as User);
			}
		} catch {
			localStorage.removeItem("user");
		}
	}, []);

	const setUser = useCallback((newUser: User) => {
		setUserState(newUser);
		localStorage.setItem("user", JSON.stringify(newUser));
	}, []);

	const clearUser = useCallback(() => {
		setUserState(null);
		localStorage.removeItem("user");
	}, []);

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

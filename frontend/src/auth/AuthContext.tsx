import React, {
  useCallback,
  useEffect,
  useState,
} from "react";
import { apiFetch, clearToken, getToken, setToken } from "../api/client";
import type { LoginResponse, User } from "../api/types";
import { AuthContext, type AuthContextValue } from "./useAuth";

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [token, setTokenState] = useState<string | null>(getToken());
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  // Synchronize user profile on initial mount if token exists
  useEffect(() => {
    let isMounted = true;
    async function loadCurrentUser() {
      const existingToken = getToken();
      if (!existingToken) {
        if (isMounted) {
          setIsLoading(false);
        }
        return;
      }

      try {
        const currentUser = await apiFetch<User>("/api/auth/me");
        if (isMounted) {
          setUser(currentUser);
          setTokenState(existingToken);
        }
      } catch {
        if (isMounted) {
          clearToken();
          setTokenState(null);
          setUser(null);
        }
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    }

    loadCurrentUser();
    return () => {
      isMounted = false;
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const res = await apiFetch<LoginResponse>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });

    setToken(res.access_token);
    setTokenState(res.access_token);
    setUser(res.user);
    return res.user;
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setTokenState(null);
    setUser(null);
  }, []);

  const value: AuthContextValue = {
    user,
    token,
    isAuthenticated: Boolean(token && user),
    isLoading,
    login,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

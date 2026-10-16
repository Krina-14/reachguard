import React, { useCallback, useEffect, useState } from "react";
import { apiFetch, clearToken, getToken, setToken } from "../api/client";
import type { LoginResponse, User } from "../api/types";
import { AuthContext, type AuthContextValue } from "./useAuth";

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [token, setTokenState] = useState<string | null>(() => getToken());
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  // On page refresh / mount: restore token from sessionStorage and validate via GET /api/auth/me
  useEffect(() => {
    let isMounted = true;

    async function validateSession() {
      const storedToken = getToken();
      if (!storedToken) {
        if (isMounted) {
          setIsLoading(false);
        }
        return;
      }

      try {
        const currentUser = await apiFetch<User>("/api/auth/me");
        if (isMounted) {
          setUser(currentUser);
          setTokenState(storedToken);
        }
      } catch {
        // Token invalid, expired, or server returned 401: clear session
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

    validateSession();

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

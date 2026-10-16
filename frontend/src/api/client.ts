/**
 * ReachGuard Typed API Client.
 * Manages in-memory / sessionStorage auth tokens and parses standard error shapes.
 * Adheres strictly to Contract Section 7. Never logs tokens.
 */

import { ApiError, type ApiErrorShape } from "./types";

// In-memory token state, synchronized with sessionStorage for page refresh survival
const SESSION_TOKEN_KEY = "reachguard_auth_token";

let inMemoryToken: string | null = ((): string | null => {
  try {
    return sessionStorage.getItem(SESSION_TOKEN_KEY);
  } catch {
    return null;
  }
})();

export function getToken(): string | null {
  return inMemoryToken;
}

export function setToken(token: string | null): void {
  inMemoryToken = token;
  try {
    if (token) {
      sessionStorage.setItem(SESSION_TOKEN_KEY, token);
    } else {
      sessionStorage.removeItem(SESSION_TOKEN_KEY);
    }
  } catch {
    // sessionStorage unavailable or restricted
  }
}

export function clearToken(): void {
  setToken(null);
}

export interface RequestOptions extends RequestInit {
  params?: Record<string, string | number | boolean | undefined | null>;
}

/**
 * Universal fetch wrapper for ReachGuard backend.
 * Automatically injects Bearer token, handles 401 session expiry,
 * and converts {"error": {code, message}} into typed ApiError instances.
 */
export async function apiFetch<T>(
  endpoint: string,
  options: RequestOptions = {}
): Promise<T> {
  const { params, headers: customHeaders, ...restOptions } = options;

  let url = endpoint;
  if (params) {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== "") {
        searchParams.append(key, String(value));
      }
    }
    const queryString = searchParams.toString();
    if (queryString) {
      url += (url.includes("?") ? "&" : "?") + queryString;
    }
  }

  const headers = new Headers(customHeaders);

  // Auto-attach JSON header unless sending multipart FormData
  if (!(restOptions.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  // Attach token from in-memory state
  const token = getToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(url, {
      ...restOptions,
      headers,
    });
  } catch (networkError) {
    throw new ApiError(
      networkError instanceof Error
        ? networkError.message
        : "Network communication failure",
      "NETWORK_ERROR",
      0
    );
  }

  // 401 Unauthorized handling: clear session and redirect to /login
  if (response.status === 401) {
    clearToken();
    if (typeof window !== "undefined" && window.location.pathname !== "/login") {
      window.location.href = "/login";
    }
  }

  // Parse response body
  if (response.status === 204) {
    return undefined as unknown as T;
  }

  let data: unknown;
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      data = await response.json();
    } catch {
      data = null;
    }
  } else {
    data = await response.text();
  }

  if (!response.ok) {
    // Parse contract error envelope: {"error": {"code": "...", "message": "..."}}
    let errCode: string | number = response.status;
    let errMsg = response.statusText || `HTTP Error ${response.status}`;

    if (
      data &&
      typeof data === "object" &&
      "error" in data &&
      typeof (data as ApiErrorShape).error === "object"
    ) {
      const envelope = (data as ApiErrorShape).error;
      errCode = envelope.code ?? response.status;
      errMsg = envelope.message || errMsg;
    } else if (typeof data === "string" && data.trim()) {
      errMsg = data;
    }

    throw new ApiError(errMsg, errCode, response.status);
  }

  return data as T;
}

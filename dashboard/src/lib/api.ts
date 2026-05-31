import axios, { AxiosError, InternalAxiosRequestConfig } from "axios";
import { getToken, getRefreshToken, setToken, removeToken } from "./auth";

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  const token = getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// --- Silent token refresh -------------------------------------------------
// On a 401 we mint a fresh access token from the refresh token (the backend
// issues a 1-day access + 7-day refresh pair) and replay the original request,
// so an expired access token no longer kicks the user out. Concurrent 401s
// share a single in-flight refresh.

let refreshPromise: Promise<string | null> | null = null;

type UnauthorizedHandler = () => void;
let onUnauthorized: UnauthorizedHandler | null = null;

/**
 * Register a soft-redirect handler (e.g. Next `router.replace`) invoked when a
 * refresh genuinely fails. Without one, api.ts falls back to a full-page load.
 */
export function registerUnauthorizedHandler(
  handler: UnauthorizedHandler | null
): void {
  onUnauthorized = handler;
}

function handleAuthFailure(): void {
  removeToken();
  if (onUnauthorized) {
    onUnauthorized();
  } else if (
    typeof window !== "undefined" &&
    window.location.pathname !== "/login"
  ) {
    window.location.assign("/login");
  }
}

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return null;
  try {
    // Bare axios (not `api`) so the interceptors below do not recurse.
    const resp = await axios.post(
      `${process.env.NEXT_PUBLIC_API_URL}/auth/refresh`,
      { refresh_token: refreshToken },
      { headers: { "Content-Type": "application/json" } }
    );
    const newAccess: string | undefined = resp.data?.access_token;
    if (!newAccess) return null;
    setToken(newAccess, resp.data?.refresh_token);
    return newAccess;
  } catch {
    return null;
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as
      | (InternalAxiosRequestConfig & { _retry?: boolean })
      | undefined;
    const status = error.response?.status;
    const detail = (error.response?.data as { detail?: unknown } | undefined)
      ?.detail;
    const isWhatsAppError =
      typeof detail === "string" && detail.includes("WhatsApp");
    const isRefreshCall = original?.url?.includes("/auth/refresh");

    // Terminal cases: not a refreshable 401, the refresh call itself failed,
    // or we already retried once.
    if (
      status !== 401 ||
      isWhatsAppError ||
      isRefreshCall ||
      !original ||
      original._retry
    ) {
      if (
        status === 401 &&
        !isWhatsAppError &&
        (isRefreshCall || original?._retry)
      ) {
        handleAuthFailure();
      }
      return Promise.reject(error);
    }

    original._retry = true;
    if (!refreshPromise) {
      refreshPromise = refreshAccessToken().finally(() => {
        refreshPromise = null;
      });
    }
    const newAccess = await refreshPromise;
    if (newAccess) {
      original.headers.Authorization = `Bearer ${newAccess}`;
      return api(original);
    }

    handleAuthFailure();
    return Promise.reject(error);
  }
);

interface FastAPIValidationError {
  loc?: ReadonlyArray<string | number>;
  msg?: string;
}

export function extractErrorMessage(
  err: unknown,
  fallback = "Request failed."
): string {
  const detail = (
    err as { response?: { data?: { detail?: unknown } } }
  )?.response?.data?.detail;

  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const parts = (detail as ReadonlyArray<FastAPIValidationError>)
      .map((item) => {
        const field = Array.isArray(item.loc)
          ? item.loc.filter((segment) => segment !== "body").join(".")
          : "";
        const msg = item.msg ?? "Invalid value";
        return field ? `${field}: ${msg}` : msg;
      })
      .filter(Boolean);
    if (parts.length > 0) return parts.join("; ");
  }

  const message = (err as { message?: string })?.message;
  return message ?? fallback;
}

export default api;

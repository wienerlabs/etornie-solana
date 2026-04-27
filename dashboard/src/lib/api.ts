import axios from "axios";
import Cookies from "js-cookie";

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  const token = Cookies.get("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const detail = error.response?.data?.detail ?? "";
      const isWhatsAppError = typeof detail === "string" && detail.includes("WhatsApp");
      if (!isWhatsAppError) {
        Cookies.remove("access_token");
        if (typeof window !== "undefined") {
          window.location.href = "/login";
        }
      }
    }
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

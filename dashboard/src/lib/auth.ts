import Cookies from "js-cookie";

const TOKEN_KEY = "access_token";
const REFRESH_KEY = "refresh_token";

// Cookies are read by JS (js-cookie) and attached to requests via the
// Authorization header, so SameSite does not affect our API calls; we set it
// to "strict" purely for CSRF hardening. `secure` is enabled whenever the app
// is served over HTTPS (a no-op on http://localhost during development).
//
// NOTE: these remain JS-readable cookies. Moving the tokens to httpOnly
// cookies set by the backend (immune to XSS token theft) is a larger
// backend + frontend change tracked separately.
function cookieOptions(): Cookies.CookieAttributes {
  const secure =
    typeof window !== "undefined" && window.location.protocol === "https:";
  return { sameSite: "strict", secure };
}

export function getToken(): string | undefined {
  return Cookies.get(TOKEN_KEY);
}

export function getRefreshToken(): string | undefined {
  return Cookies.get(REFRESH_KEY);
}

export function setToken(accessToken: string, refreshToken?: string): void {
  Cookies.set(TOKEN_KEY, accessToken, { ...cookieOptions(), expires: 1 });
  if (refreshToken) {
    Cookies.set(REFRESH_KEY, refreshToken, { ...cookieOptions(), expires: 7 });
  }
}

export function removeToken(): void {
  Cookies.remove(TOKEN_KEY);
  Cookies.remove(REFRESH_KEY);
}

export function isLoggedIn(): boolean {
  return !!Cookies.get(TOKEN_KEY);
}

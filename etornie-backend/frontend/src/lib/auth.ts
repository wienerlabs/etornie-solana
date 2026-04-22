import Cookies from "js-cookie";

const TOKEN_KEY = "access_token";
const REFRESH_KEY = "refresh_token";

export function getToken(): string | undefined {
  return Cookies.get(TOKEN_KEY);
}

export function setToken(accessToken: string, refreshToken?: string): void {
  Cookies.set(TOKEN_KEY, accessToken, { expires: 1 });
  if (refreshToken) {
    Cookies.set(REFRESH_KEY, refreshToken, { expires: 7 });
  }
}

export function removeToken(): void {
  Cookies.remove(TOKEN_KEY);
  Cookies.remove(REFRESH_KEY);
}

export function isLoggedIn(): boolean {
  return !!Cookies.get(TOKEN_KEY);
}

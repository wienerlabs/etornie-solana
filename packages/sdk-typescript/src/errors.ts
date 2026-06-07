/** Error thrown when the Etornie API returns a non-2xx response. */
export class EtornieApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? `Etornie API error ${status}`);
    this.name = "EtornieApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** Error thrown when a request is made without authentication. */
export class EtornieAuthError extends Error {
  constructor(message = "No access token set. Call auth.login() or pass a token.") {
    super(message);
    this.name = "EtornieAuthError";
  }
}

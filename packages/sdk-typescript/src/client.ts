import { EtornieApiError, EtornieAuthError } from "./errors.js";
import type {
  Case,
  CaseListResponse,
  CalendarFeedStatus,
  CreateCaseInput,
  DataExportFormat,
  DocumentListResponse,
  ListCasesParams,
  RenewalStatus,
  TokenResponse,
  UpdateCaseInput,
  User,
} from "./types.js";

export interface EtornieClientOptions {
  /** Base URL of the Etornie API, e.g. https://api.etornie.com */
  baseUrl: string;
  /** Optional bearer access token (or set later via auth.login). */
  token?: string;
  /** Custom fetch implementation (defaults to global fetch). */
  fetch?: typeof fetch;
}

type RequestOptions = {
  method?: string;
  query?: Record<string, string | number | undefined>;
  body?: unknown;
  auth?: boolean;
  raw?: boolean;
};

/**
 * Typed client for the Etornie API.
 *
 * ```ts
 * const etornie = new EtornieClient({ baseUrl: "https://api.etornie.com" });
 * await etornie.auth.login("you@example.com", "password");
 * const { cases } = await etornie.cases.list({ status: "open" });
 * ```
 */
export class EtornieClient {
  readonly baseUrl: string;
  private token?: string;
  private readonly fetchImpl: typeof fetch;

  readonly auth: AuthResource;
  readonly cases: CasesResource;
  readonly documents: DocumentsResource;
  readonly renewals: RenewalsResource;
  readonly calendar: CalendarResource;
  readonly dataExport: DataExportResource;

  constructor(options: EtornieClientOptions) {
    if (!options.baseUrl) throw new Error("baseUrl is required");
    this.baseUrl = options.baseUrl.replace(/\/$/, "");
    this.token = options.token;
    const f = options.fetch ?? globalThis.fetch;
    if (!f) {
      throw new Error(
        "No fetch implementation available. Pass options.fetch (Node < 18)."
      );
    }
    this.fetchImpl = f;

    this.auth = new AuthResource(this);
    this.cases = new CasesResource(this);
    this.documents = new DocumentsResource(this);
    this.renewals = new RenewalsResource(this);
    this.calendar = new CalendarResource(this);
    this.dataExport = new DataExportResource(this);
  }

  /** Set or replace the bearer access token. */
  setToken(token: string | undefined): void {
    this.token = token;
  }

  /** The current access token, if any. */
  getToken(): string | undefined {
    return this.token;
  }

  /** Low-level request helper. Most callers use the resource methods. */
  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const { method = "GET", query, body, auth = true, raw = false } = options;

    const url = new URL(this.baseUrl + path);
    if (query) {
      for (const [key, value] of Object.entries(query)) {
        if (value !== undefined) url.searchParams.set(key, String(value));
      }
    }

    const headers: Record<string, string> = { Accept: "application/json" };
    if (auth) {
      if (!this.token) throw new EtornieAuthError();
      headers.Authorization = `Bearer ${this.token}`;
    }
    if (body !== undefined) headers["Content-Type"] = "application/json";

    const res = await this.fetchImpl(url.toString(), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });

    if (!res.ok) {
      let detail: unknown = undefined;
      try {
        detail = (await res.json())?.detail;
      } catch {
        detail = await res.text().catch(() => undefined);
      }
      throw new EtornieApiError(res.status, detail);
    }

    if (raw) return (await res.arrayBuffer()) as unknown as T;
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }

  /** Request returning the raw response bytes (downloads). */
  async requestBytes(
    path: string,
    options: RequestOptions = {}
  ): Promise<ArrayBuffer> {
    return this.request<ArrayBuffer>(path, { ...options, raw: true });
  }
}

class AuthResource {
  constructor(private readonly client: EtornieClient) {}

  /** Exchange email + password for tokens and store the access token. */
  async login(email: string, password: string): Promise<TokenResponse> {
    const tokens = await this.client.request<TokenResponse>("/auth/login", {
      method: "POST",
      auth: false,
      body: { email, password },
    });
    this.client.setToken(tokens.access_token);
    return tokens;
  }

  /** The authenticated user. */
  async me(): Promise<User> {
    return this.client.request<User>("/auth/me");
  }
}

class CasesResource {
  constructor(private readonly client: EtornieClient) {}

  list(params: ListCasesParams = {}): Promise<CaseListResponse> {
    return this.client.request<CaseListResponse>("/cases", {
      query: { skip: params.skip, limit: params.limit, status: params.status },
    });
  }

  get(caseId: string): Promise<Case> {
    return this.client.request<Case>(`/cases/${caseId}`);
  }

  /** Create a case (requires an admin token). */
  async create(input: CreateCaseInput): Promise<Case> {
    const res = await this.client.request<{ case: Case }>("/cases", {
      method: "POST",
      body: input,
    });
    return res.case;
  }

  update(caseId: string, input: UpdateCaseInput): Promise<Case> {
    return this.client.request<Case>(`/cases/${caseId}`, {
      method: "PATCH",
      body: input,
    });
  }
}

class DocumentsResource {
  constructor(private readonly client: EtornieClient) {}

  list(caseId: string): Promise<DocumentListResponse> {
    return this.client.request<DocumentListResponse>(
      `/cases/${caseId}/documents`
    );
  }

  /** Download a document's bytes. */
  download(documentId: string): Promise<ArrayBuffer> {
    return this.client.requestBytes(`/documents/${documentId}/download`);
  }
}

class RenewalsResource {
  constructor(private readonly client: EtornieClient) {}

  status(caseId: string): Promise<RenewalStatus> {
    return this.client.request<RenewalStatus>(`/cases/${caseId}/renewal-status`);
  }
}

class CalendarResource {
  constructor(private readonly client: EtornieClient) {}

  status(): Promise<CalendarFeedStatus> {
    return this.client.request<CalendarFeedStatus>("/calendar/feed");
  }

  enable(): Promise<CalendarFeedStatus> {
    return this.client.request<CalendarFeedStatus>("/calendar/feed", {
      method: "POST",
    });
  }

  rotate(): Promise<CalendarFeedStatus> {
    return this.client.request<CalendarFeedStatus>("/calendar/feed/rotate", {
      method: "POST",
    });
  }

  async disable(): Promise<void> {
    await this.client.request<void>("/calendar/feed", { method: "DELETE" });
  }
}

class DataExportResource {
  constructor(private readonly client: EtornieClient) {}

  /** Download the authenticated user's GDPR data export (Article 20). */
  download(format: DataExportFormat = "json"): Promise<ArrayBuffer> {
    return this.client.requestBytes("/users/me/export", { query: { format } });
  }
}

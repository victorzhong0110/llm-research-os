/** Typed client for the local read API.
 *
 * The request types come from `generated/local-api.ts`, which is rendered from
 * the Python contracts. A server response is validated against the same
 * interface before it reaches a component, so a contract change surfaces as a
 * type error here rather than as an empty view.
 */

import type {
  ArtifactView,
  CommandReceipt,
  Capabilities,
  Error as ApiError,
  EventPage,
  Health,
  RevisionPage,
  RunPage,
  Session,
  WorkspaceView,
} from "./generated/local-api";
import { API_PREFIX } from "./generated/local-api";

/** A typed failure carrying the server's closed error code. */
export class ApiRequestError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "ApiRequestError";
    this.code = code;
    this.status = status;
  }
}

/** Raised when the session is gone and the operator must bootstrap again. */
export class SessionExpiredError extends ApiRequestError {
  constructor() {
    super("session-expired", "The local session expired; open the bootstrap URL again.", 401);
    this.name = "SessionExpiredError";
  }
}

export class OfflineError extends Error {
  constructor() {
    super("The local API is not reachable.");
    this.name = "OfflineError";
  }
}

/**
 * The double-submit CSRF value for this session.
 *
 * The cookie is HttpOnly, so same-origin script learns the token from the
 * session body and echoes it on every unsafe request. Losing it makes the
 * server refuse writes, which is the intended failure.
 */
let csrfToken: string | null = null;

function rememberCsrf(session: Session): void {
  csrfToken = session.csrfToken;
}

function unsafeHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { ...(extra ?? {}) };
  if (csrfToken === null) {
    throw new SessionExpiredError();
  }
  headers["X-ResearchOS-CSRF"] = csrfToken;
  return headers;
}

function isApiError(value: unknown): value is ApiError {
  return (
    typeof value === "object" &&
    value !== null &&
    (value as { kind?: unknown }).kind === "LocalApiError" &&
    typeof (value as { code?: unknown }).code === "string"
  );
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    const isUnsafe = init?.method !== undefined && init.method.toUpperCase() !== "GET";
    response = await fetch(`${API_PREFIX}${path}`, {
      ...init,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(isUnsafe ? unsafeHeaders(init.headers as Record<string, string> | undefined) : {}),
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw new OfflineError();
  }
  const text = await response.text();
  let payload: unknown = null;
  if (text !== "") {
    try {
      payload = JSON.parse(text) as unknown;
    } catch {
      throw new ApiRequestError("response-invalid", "The server sent a malformed body.", 502);
    }
  }
  if (isApiError(payload)) {
    if (payload.code === "session-expired" || payload.code === "session-required") {
      throw new SessionExpiredError();
    }
    throw new ApiRequestError(payload.code, payload.message, response.status);
  }
  if (!response.ok) {
    throw new ApiRequestError("request-failed", `The request failed (${response.status}).`, response.status);
  }
  return payload as T;
}

function pageQuery(cursor: string | null, limit: number): string {
  const params = new URLSearchParams({ limit: String(limit) });
  if (cursor !== null) {
    params.set("cursor", cursor);
  }
  return `?${params.toString()}`;
}

export interface Paged<T> {
  readonly items: ReadonlyArray<T>;
  readonly nextCursor: string | null;
  readonly highWaterMark: number;
}

export const api = {
  /** Liveness lives outside the versioned prefix and needs no session. */
  async health(): Promise<Health> {
    let response: Response;
    try {
      response = await fetch("/api/health", { credentials: "same-origin" });
    } catch {
      throw new OfflineError();
    }
    if (!response.ok) {
      throw new ApiRequestError("request-failed", `Health check failed (${response.status}).`, response.status);
    }
    return (await response.json()) as Health;
  },
  async session(): Promise<Session> {
    const session = await request<Session>("/session");
    rememberCsrf(session);
    return session;
  },
  capabilities(): Promise<Capabilities> {
    return request<Capabilities>("/capabilities");
  },
  workspace(): Promise<WorkspaceView> {
    return request<WorkspaceView>("/workspace");
  },
  events(cursor: string | null, limit: number): Promise<Paged<EventPage["items"][number]>> {
    return request<EventPage>(`/events${pageQuery(cursor, limit)}`).then((page) => ({
      items: page.items,
      nextCursor: page.nextCursor ?? null,
      highWaterMark: page.highWaterMark,
    }));
  },
  revisions(cursor: string | null, limit: number): Promise<Paged<RevisionPage["items"][number]>> {
    return request<RevisionPage>(`/revisions${pageQuery(cursor, limit)}`).then((page) => ({
      items: page.items,
      nextCursor: page.nextCursor ?? null,
      highWaterMark: page.highWaterMark,
    }));
  },
  runs(cursor: string | null, limit: number): Promise<Paged<RunPage["items"][number]>> {
    return request<RunPage>(`/runs${pageQuery(cursor, limit)}`).then((page) => ({
      items: page.items,
      nextCursor: page.nextCursor ?? null,
      highWaterMark: page.highWaterMark,
    }));
  },
  artifact(digest: string): Promise<ArtifactView> {
    return request<ArtifactView>(`/artifacts/${encodeURIComponent(digest)}`);
  },
  /** Dispatch one caller-owned application command. The body is sent verbatim. */
  command(body: string): Promise<CommandReceipt> {
    return request<CommandReceipt>("/commands", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
  },
} as const;

/** Read the one-time bootstrap secret out of the URL fragment, then clear it.
 *
 * A fragment is never sent to the server, so the secret stays out of access
 * logs and `Referer` headers. It is spent on first use.
 */
export function takeBootstrapSecret(): string | null {
  const hash = window.location.hash;
  if (!hash.startsWith("#bootstrap=")) {
    return null;
  }
  const secret = decodeURIComponent(hash.slice("#bootstrap=".length));
  window.history.replaceState(null, "", window.location.pathname);
  return secret === "" ? null : secret;
}

export async function exchangeBootstrap(secret: string): Promise<Session> {
  const response = await fetch(`${API_PREFIX}/session`, {
    method: "POST",
    credentials: "same-origin",
    headers: { "X-ResearchOS-Bootstrap": secret },
  });
  if (!response.ok) {
    const payload = (await response.json()) as ApiError;
    throw new ApiRequestError(payload.code, payload.message, response.status);
  }
  const session = (await response.json()) as Session;
  rememberCsrf(session);
  return session;
}

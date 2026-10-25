import { API_URL } from "./config";
import type { RunCreated, RunRecord } from "./types";

/** Error raised for non-2xx API responses, with the backend message if present. */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Extract a human-readable message from an error response body. */
function extractMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object") {
    const detail = (body as Record<string, unknown>).detail;
    if (detail && typeof detail === "object") {
      const message = (detail as Record<string, unknown>).message;
      if (typeof message === "string" && message) return message;
    }
    if (typeof detail === "string" && detail) return detail;
    const message = (body as Record<string, unknown>).message;
    if (typeof message === "string" && message) return message;
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    cache: "no-store",
  });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      message = extractMessage(await response.json(), message);
    } catch {
      // non-JSON error body; keep the fallback message
    }
    throw new ApiError(response.status, message);
  }

  return (await response.json()) as T;
}

export type CreateRunPayload =
  | { issue_url: string }
  | { repo_url: string; task: string };

/** POST /api/runs — enqueue a run; returns 202 with the new run id. */
export function createRun(payload: CreateRunPayload): Promise<RunCreated> {
  return request<RunCreated>("/api/runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** GET /api/runs/{runId} — fetch the full run record. */
export function getRun(runId: string): Promise<RunRecord> {
  return request<RunRecord>(`/api/runs/${encodeURIComponent(runId)}`);
}

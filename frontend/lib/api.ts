import type { AgentEvent, Dashboard, ExperimentDetail, ExperimentSummary, Health } from "@/types";

// Accepts a full URL or a bare hostname (Render's blueprint passes hostnames, e.g. "api.onrender.com").
const rawApiUrl = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
export const API_URL = rawApiUrl.includes("://") ? rawApiUrl : `https://${rawApiUrl}`;

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(0, `Cannot reach the ExperimentOS backend at ${API_URL}. Is it running?`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail
        : typeof body.detail?.message === "string" ? body.detail.message
        : Array.isArray(body.detail) ? body.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ")
        : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/health"),
  listExperiments: () => request<{ items: ExperimentSummary[]; dashboard: Dashboard }>("/experiments"),
  /** withEvents=false skips the event log (live views receive events over SSE instead). */
  getExperiment: (id: string, withEvents = true) =>
    request<ExperimentDetail>(`/experiments/${id}${withEvents ? "" : "?events=false"}`),
  getResults: (id: string) => request<Record<string, unknown>>(`/experiments/${id}/results`),
  createExperiment: (research_question: string, use_research = true) =>
    request<ExperimentSummary>("/experiments", {
      method: "POST",
      body: JSON.stringify({ research_question, use_research }),
    }),
  runFeatured: () => request<ExperimentSummary>("/experiments/featured", { method: "POST" }),
  runNext: (id: string) => request<ExperimentSummary>(`/experiments/${id}/next`, { method: "POST" }),
  cancel: (id: string) => request<ExperimentSummary>(`/experiments/${id}/cancel`, { method: "POST" }),
  listDatasets: () => request<{ items: Record<string, unknown>[] }>("/datasets"),
  getDataset: (id: string) => request<Record<string, unknown>>(`/datasets/${id}`),
};

/** Subscribe to the live agent event stream (SSE). Returns an unsubscribe function. */
export function subscribeEvents(
  id: string,
  afterId: number,
  onEvent: (e: AgentEvent) => void,
  onEnd: () => void,
): () => void {
  const es = new EventSource(`${API_URL}/experiments/${id}/events?after=${afterId}`);
  es.addEventListener("agent", (msg) => {
    try {
      onEvent(JSON.parse((msg as MessageEvent).data));
    } catch {
      /* ignore malformed */
    }
  });
  es.addEventListener("end", () => {
    es.close();
    onEnd();
  });
  return () => es.close();
}

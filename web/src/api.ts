import type { Investigation, Policy, AuditEvent, IntegrationStatus } from "./types";

const BASE = "/api";

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      /* response had no JSON body */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => json<{ status: string; any_live: boolean; policy_version: string }>("/health"),
  integrations: () => json<IntegrationStatus[]>("/integrations"),
  policy: () => json<Policy>("/policy"),
  workflow: () => json<{ sequence: string[]; escalations: string[] }>("/workflow"),

  listRuns: () =>
    json<{ id: string; status: string; target: string; created_at: string }[]>("/investigations"),

  seedDemo: () =>
    json<{ run_id: string }>("/demo/seed?autostart=true", { method: "POST" }),

  create: (body: Record<string, unknown>) =>
    json<Investigation>("/investigations", { method: "POST", body: JSON.stringify(body) }),

  get: (id: string) => json<Investigation>(`/investigations/${id}`),
  audit: (id: string) => json<AuditEvent[]>(`/investigations/${id}/audit`),

  start: (id: string) => json<unknown>(`/investigations/${id}/start`, { method: "POST" }),
  challenge: (id: string) => json<unknown>(`/investigations/${id}/challenge`, { method: "POST" }),
  redesign: (id: string, candidateId?: string) =>
    json<unknown>(
      `/investigations/${id}/redesign${candidateId ? `/${candidateId}` : ""}`,
      { method: "POST" },
    ),
  finalize: (id: string) => json<unknown>(`/investigations/${id}/finalize`, { method: "POST" }),

  dossier: (id: string) =>
    json<{ markdown: string; redesign_delta: string }>(`/investigations/${id}/dossier`),

  requestBenchling: (id: string) =>
    json<unknown>(`/investigations/${id}/request-benchling-write`, { method: "POST" }),
  approveBenchling: (id: string, approver: string) =>
    json<unknown>(`/investigations/${id}/approve-benchling-write`, {
      method: "POST",
      body: JSON.stringify({ approver, confirm: true }),
    }),

  artifactUrl: (runId: string, artifactId: string) =>
    `${BASE}/investigations/${runId}/artifacts/${artifactId}`,

  eventsUrl: (id: string) => `${BASE}/investigations/${id}/events`,
};

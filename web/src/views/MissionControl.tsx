import { useState } from "react";
import { api } from "../api";
import {
  Button,
  Card,
  Empty,
  ModeChip,
  SectionTitle,
  StatTile,
} from "../components/primitives";
import type { AuditEvent, IntegrationStatus, Investigation } from "../types";

export function MissionControl({
  investigation,
  audit,
  integrations,
  connected,
  onAction,
}: {
  investigation: Investigation | null;
  audit: AuditEvent[];
  integrations: IntegrationStatus[];
  connected: boolean;
  onAction: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);

  const start = async () => {
    if (!investigation) return;
    setBusy(true);
    try {
      await api.start(investigation.id);
      onAction("Investigation started.");
    } catch (err) {
      onAction(`Failed: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const counts = investigation
    ? {
        evidence: investigation.evidence.length,
        candidates: investigation.candidates.length,
        rejected: investigation.candidates.filter((c) => c.status === "rejected").length,
        recommended: investigation.candidates.filter((c) => c.status === "recommended").length,
      }
    : { evidence: 0, candidates: 0, rejected: 0, recommended: 0 };

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
      <div className="space-y-5">
        {investigation ? (
          <Card className="p-5">
            <div className="flex flex-wrap items-start gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <h1 className="text-xl font-semibold">{investigation.target.name}</h1>
                  {investigation.target.uniprot_id && (
                    <a
                      className="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-[11px] text-s1 hover:brightness-125"
                      href={`https://www.uniprot.org/uniprotkb/${investigation.target.uniprot_id}/entry`}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      {investigation.target.uniprot_id}
                    </a>
                  )}
                  {investigation.target.pdb_id && (
                    <a
                      className="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-[11px] text-s1 hover:brightness-125"
                      href={`https://www.rcsb.org/structure/${investigation.target.pdb_id}`}
                      target="_blank"
                      rel="noreferrer noopener"
                    >
                      PDB {investigation.target.pdb_id}
                    </a>
                  )}
                </div>
                <p className="mt-2 text-[13px] leading-relaxed text-ink-2">
                  <span className="text-ink-3">Epitope: </span>
                  {investigation.target.epitope_description}
                </p>
                <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-[12px] sm:grid-cols-4">
                  <Field label="Format" value={investigation.target_product_profile.format} />
                  <Field
                    label="Candidates"
                    value={String(investigation.target_product_profile.max_candidates)}
                  />
                  <Field
                    label="Max finalists"
                    value={String(investigation.target_product_profile.max_finalists)}
                  />
                  <Field label="Seed" value={String(investigation.seed)} />
                  <Field label="Run" value={investigation.id} mono />
                  <Field label="Policy" value={investigation.policy_version} mono />
                  <Field label="Run mode" value={investigation.mode} />
                  <Field
                    label="Stream"
                    value={connected ? "connected" : "disconnected"}
                    tone={connected ? "good" : "warning"}
                  />
                </dl>
              </div>

              {investigation.status === "CREATED" && (
                <Button variant="primary" onClick={start} disabled={busy}>
                  ▶ Start investigation
                </Button>
              )}
            </div>
          </Card>
        ) : (
          <Empty>
            No investigation loaded. Use <strong>Seed VEGF-A demo</strong> in the header.
          </Empty>
        )}

        <div className="grid gap-3 sm:grid-cols-4">
          <StatTile label="Evidence" value={counts.evidence} />
          <StatTile label="Candidates" value={counts.candidates} />
          <StatTile label="Rejected" value={counts.rejected} tone="critical" />
          <StatTile label="Recommended" value={counts.recommended} tone="good" />
        </div>

        <Card className="p-4">
          <SectionTitle hint={`${audit.length} immutable events`}>Audit trail</SectionTitle>
          {audit.length === 0 ? (
            <Empty>Nothing recorded yet.</Empty>
          ) : (
            <ol className="max-h-[440px] space-y-1.5 overflow-y-auto pr-1">
              {[...audit].reverse().map((event) => (
                <li
                  key={event.id}
                  className="bf-rise rounded-md border border-hair bg-surface-2 px-3 py-2"
                >
                  <div className="flex flex-wrap items-center gap-2 text-[11px] text-ink-3">
                    <span className="font-mono tabular-nums">#{event.seq}</span>
                    <span className="font-mono">{event.timestamp.slice(11, 19)}</span>
                    <span
                      className={`rounded px-1.5 py-0.5 font-medium ${kindStyle(event.kind)}`}
                    >
                      {event.kind.replace("_", " ")}
                    </span>
                    {event.next_state && (
                      <span className="font-mono text-ink-2">
                        {event.prev_state ? `${event.prev_state} → ` : ""}
                        {event.next_state}
                      </span>
                    )}
                    {event.mode && <ModeChip mode={event.mode} />}
                    <span className="ml-auto">{event.actor}</span>
                  </div>
                  <p className="mt-1 text-[12.5px] leading-snug text-ink-2">{event.summary}</p>
                  {event.warning && (
                    <p className="mt-1 text-[11.5px] text-warning">⚠ {event.warning}</p>
                  )}
                  {event.error && (
                    <p className="mt-1 text-[11.5px] text-critical">✕ {event.error}</p>
                  )}
                </li>
              ))}
            </ol>
          )}
        </Card>
      </div>

      <div className="space-y-4">
        <Card className="p-4">
          <SectionTitle hint="per adapter">Integrations</SectionTitle>
          <div className="space-y-2.5">
            {integrations.map((status) => (
              <div key={status.name} className="rounded-md border border-hair bg-surface-2 p-2.5">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-[12.5px] text-ink">{status.name}</span>
                  <span className="ml-auto">
                    <ModeChip mode={status.mode} />
                  </span>
                </div>
                <p className="mt-1 text-[11.5px] leading-snug text-ink-3">{status.detail}</p>
                {status.mode !== "live" && status.requirement && (
                  <p className="mt-1 border-t border-hair pt-1 text-[11px] leading-snug text-ink-3/80">
                    <span className="text-ink-3">To enable live: </span>
                    {status.requirement}
                  </p>
                )}
                {status.last_error && (
                  <p className="mt-1 text-[11px] text-critical">✕ {status.last_error}</p>
                )}
              </div>
            ))}
          </div>
        </Card>

        <Card className="border-warning/35 bg-warning/6 p-4">
          <SectionTitle>Scope</SectionTitle>
          <p className="text-[12.5px] leading-relaxed text-ink-2">
            Everything this system produces is a computational prediction. No candidate has been
            expressed, purified, or tested. The output is a prioritised shortlist and an
            experiment-ready handoff — not evidence that any molecule binds anything.
          </p>
        </Card>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  mono,
  tone,
}: {
  label: string;
  value: string;
  mono?: boolean;
  tone?: "good" | "warning";
}) {
  return (
    <div>
      <dt className="text-[10.5px] uppercase tracking-wider text-ink-3">{label}</dt>
      <dd
        className={`${mono ? "font-mono" : ""} ${
          tone === "good" ? "text-good" : tone === "warning" ? "text-warning" : "text-ink-2"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

function kindStyle(kind: string): string {
  switch (kind) {
    case "state_transition":
      return "bg-s1/15 text-s1";
    case "decision":
      return "bg-s7/18 text-s7";
    case "tool_call":
      return "bg-surface-3 text-ink-2";
    case "human_action":
      return "bg-good/15 text-good";
    case "error":
      return "bg-critical/18 text-critical";
    default:
      return "bg-surface-3 text-ink-3";
  }
}

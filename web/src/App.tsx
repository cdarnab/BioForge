import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { Timeline } from "./components/Timeline";
import { Button, ModeChip } from "./components/primitives";
import { useRun } from "./hooks/useRun";
import { CandidateCourt } from "./views/CandidateCourt";
import { DecisionDossier } from "./views/DecisionDossier";
import { EvidenceBoard } from "./views/EvidenceBoard";
import { HypothesisLedger } from "./views/HypothesisLedger";
import { MissionControl } from "./views/MissionControl";
import type { IntegrationStatus } from "./types";

type View = "mission" | "evidence" | "hypotheses" | "court" | "dossier";

const VIEWS: { key: View; label: string; hint: string }[] = [
  { key: "mission", label: "Mission Control", hint: "target, integrations, audit" },
  { key: "evidence", label: "Evidence Board", hint: "cited, with contradictions first" },
  { key: "hypotheses", label: "Hypothesis Ledger", hint: "falsifiable, with results" },
  { key: "court", label: "Candidate Court", hint: "four gates, live" },
  { key: "dossier", label: "Decision Dossier", hint: "shortlist and handoff" },
];

const RUN_KEY = "bioforge.runId";

export default function App() {
  const [runId, setRunId] = useState<string | null>(() => localStorage.getItem(RUN_KEY));
  const [view, setView] = useState<View>("mission");
  const [integrations, setIntegrations] = useState<IntegrationStatus[]>([]);
  const [toast, setToast] = useState<string | null>(null);
  const [seeding, setSeeding] = useState(false);

  const { investigation, audit, connected, flashed, refresh } = useRun(runId);

  useEffect(() => {
    void api.integrations().then(setIntegrations).catch(() => setIntegrations([]));
  }, []);

  useEffect(() => {
    if (runId) localStorage.setItem(RUN_KEY, runId);
  }, [runId]);

  const notify = useCallback((message: string) => {
    setToast(message);
    window.setTimeout(() => setToast(null), 3200);
  }, []);

  const seed = async () => {
    setSeeding(true);
    try {
      const { run_id } = await api.seedDemo();
      setRunId(run_id);
      setView("mission");
      notify("VEGF-A demo seeded and running.");
    } catch (err) {
      notify(`Failed: ${(err as Error).message}`);
    } finally {
      setSeeding(false);
    }
  };

  // Jump the operator to the view where the action is, once per phase change.
  useEffect(() => {
    if (!investigation) return;
    if (investigation.status === "PRIMARY_TESTING") setView((v) => (v === "hypotheses" ? "court" : v));
    if (investigation.status === "HYPOTHESES_CREATED")
      setView((v) => (v === "evidence" ? "hypotheses" : v));
    if (investigation.status === "EVIDENCE_GATHERING")
      setView((v) => (v === "mission" ? "evidence" : v));
  }, [investigation?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const liveCount = integrations.filter((i) => i.mode === "live").length;

  return (
    <div className="flex min-h-full flex-col bg-plane">
      <header className="border-b border-hair bg-surface/80 px-6 py-3 backdrop-blur">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2.5">
            <span className="grid h-7 w-7 place-items-center rounded bg-s1 text-sm font-bold text-white">
              BJ
            </span>
            <div>
              <div className="text-[15px] font-semibold leading-tight">BioForge Judge</div>
              <div className="text-[11px] leading-tight text-ink-3">
                It tries to prove its own candidates wrong before recommending them.
              </div>
            </div>
          </div>

          <div className="ml-auto flex flex-wrap items-center gap-2">
            <span
              className="rounded-md border border-warning/40 bg-warning/10 px-2 py-1 text-[11px] font-medium text-warning"
              title="No number in this product is an experimental measurement."
            >
              predictions only — not experimental validation
            </span>
            <span
              className="rounded-md border border-rule bg-surface-2 px-2 py-1 text-[11px] text-ink-3"
              title={integrations.map((i) => `${i.name}: ${i.mode}`).join("\n")}
            >
              {liveCount > 0 ? (
                <span className="text-good">{liveCount} live</span>
              ) : (
                <span>all fixture</span>
              )}{" "}
              / {integrations.length} integrations
            </span>
            <span
              className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] ${
                connected
                  ? "border-good/40 bg-good/10 text-good"
                  : "border-rule bg-surface-2 text-ink-3"
              }`}
            >
              <span
                className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-good bf-pulse" : "bg-ink-3"}`}
              />
              {connected ? "live stream" : "idle"}
            </span>
            <Button variant="primary" onClick={seed} disabled={seeding}>
              {seeding ? "Seeding…" : "Seed VEGF-A demo"}
            </Button>
            {investigation && (
              <Button variant="ghost" onClick={() => void refresh()} title="Refetch from the API">
                ⟳
              </Button>
            )}
          </div>
        </div>

        <nav className="mt-3 flex flex-wrap gap-1">
          {VIEWS.map((item) => (
            <button
              key={item.key}
              onClick={() => setView(item.key)}
              title={item.hint}
              className={`rounded-md px-3 py-1.5 text-[13px] transition ${
                view === item.key
                  ? "bg-surface-3 font-semibold text-ink"
                  : "text-ink-3 hover:bg-surface-2 hover:text-ink-2"
              }`}
            >
              {item.label}
              {item.key === "court" && investigation && (
                <span className="ml-1.5 rounded bg-s1/20 px-1 text-[10px] font-semibold text-s1">
                  {investigation.candidates.length}
                </span>
              )}
            </button>
          ))}
        </nav>
      </header>

      {investigation && (
        <Timeline status={investigation.status} detail={investigation.status_detail} />
      )}

      <main className="flex-1 px-6 py-5">
        {view === "mission" && (
          <MissionControl
            investigation={investigation}
            audit={audit}
            integrations={
              investigation?.integrations.length ? investigation.integrations : integrations
            }
            connected={connected}
            onAction={notify}
          />
        )}
        {investigation && view === "evidence" && <EvidenceBoard investigation={investigation} />}
        {investigation && view === "hypotheses" && (
          <HypothesisLedger investigation={investigation} />
        )}
        {investigation && view === "court" && (
          <CandidateCourt
            investigation={investigation}
            flashed={flashed}
            onAction={notify}
          />
        )}
        {investigation && view === "dossier" && (
          <DecisionDossier investigation={investigation} onAction={notify} />
        )}
        {!investigation && view !== "mission" && (
          <p className="text-sm text-ink-3">Seed or load an investigation first.</p>
        )}
      </main>

      <footer className="border-t border-hair px-6 py-2.5 text-[11px] text-ink-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span>
            Policy <span className="font-mono">{investigation?.policy_version ?? "—"}</span> ·
            thresholds are uncalibrated demonstration values
          </span>
          <span className="ml-auto flex items-center gap-2">
            {integrations.slice(0, 7).map((i) => (
              <span key={i.name} className="inline-flex items-center gap-1">
                <ModeChip mode={i.mode} />
                <span className="font-mono">{i.name}</span>
              </span>
            ))}
          </span>
        </div>
      </footer>

      {toast && (
        <div className="bf-rise fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-md border border-rule bg-surface-3 px-4 py-2.5 text-sm shadow-xl">
          {toast}
        </div>
      )}
    </div>
  );
}

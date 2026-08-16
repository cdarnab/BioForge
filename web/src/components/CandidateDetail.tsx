import { GATE_LABEL, GATE_ORDER, type Candidate, type Investigation } from "../types";
import { GateBar } from "./GateBar";
import { MetricRow } from "./MetricRow";
import { Button, PredictionBadge } from "./primitives";

export function CandidateDetail({
  candidate,
  investigation,
  onClose,
  onSelect,
}: {
  candidate: Candidate;
  investigation: Investigation;
  onClose: () => void;
  onSelect: (id: string) => void;
}) {
  const parent = candidate.parent_id
    ? investigation.candidates.find((c) => c.id === candidate.parent_id)
    : null;
  const child = investigation.candidates.find((c) => c.parent_id === candidate.id);
  const failedGate = candidate.gates.find((g) => !g.passed);
  const nextStep = investigation.narrative[`next_step_${candidate.id}`];

  return (
    <aside className="fixed inset-y-0 right-0 z-40 flex w-full max-w-[560px] flex-col border-l border-rule bg-plane shadow-2xl">
      <header className="flex items-start justify-between gap-4 border-b border-hair px-5 py-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <h2 className="text-lg font-semibold">{candidate.name}</h2>
            <StatusPill status={candidate.status} />
            {candidate.rank && (
              <span className="rounded bg-s1/15 px-1.5 py-0.5 text-[11px] font-semibold text-s1">
                rank {candidate.rank}
              </span>
            )}
          </div>
          <p className="mt-1 text-xs text-ink-3">{candidate.generation_note}</p>
        </div>
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      </header>

      <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
        <section>
          <GateBar gates={candidate.gates} />
          <div className="mt-2 space-y-1">
            {GATE_ORDER.map((name) => {
              const outcome = candidate.gates.find((g) => g.gate === name);
              return (
                <div key={name} className="flex items-start gap-2 text-xs">
                  <span
                    className={`mt-0.5 w-4 shrink-0 text-center font-bold ${
                      !outcome ? "text-ink-3" : outcome.passed ? "text-good" : "text-critical"
                    }`}
                  >
                    {!outcome ? "–" : outcome.passed ? "✓" : "✕"}
                  </span>
                  <span className="w-40 shrink-0 text-ink-2">{GATE_LABEL[name]}</span>
                  <span className="text-ink-3">
                    {outcome ? outcome.reason : "not run for this candidate"}
                  </span>
                </div>
              );
            })}
          </div>
        </section>

        {(parent || child) && (
          <section className="rounded-md border border-s7/40 bg-s7/8 p-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-s7">
              Lineage
            </h3>
            {parent && (
              <p className="mt-1 text-xs text-ink-2">
                Redesigned from{" "}
                <button
                  className="font-mono text-s1 underline underline-offset-2"
                  onClick={() => onSelect(parent.id)}
                >
                  {parent.id}
                </button>
                , which was rejected at the{" "}
                {parent.gates.find((g) => !g.passed)?.gate.replace("_", " ")} gate.
              </p>
            )}
            {child && (
              <p className="mt-1 text-xs text-ink-2">
                Redesigned into{" "}
                <button
                  className="font-mono text-s1 underline underline-offset-2"
                  onClick={() => onSelect(child.id)}
                >
                  {child.id}
                </button>
                .
              </p>
            )}
          </section>
        )}

        <section>
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-2">
            Decision
          </h3>
          <div className="rounded-md border border-hair bg-surface p-3">
            <div className="mb-2 flex flex-wrap gap-1">
              {candidate.decision.reason_codes.map((code) => (
                <span
                  key={code}
                  className="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-[10px] text-ink-2"
                >
                  {code}
                </span>
              ))}
            </div>
            <p className="text-[13px] leading-relaxed text-ink-2">
              {candidate.decision.summary}
            </p>
            {failedGate && (
              <p className="mt-2 text-xs text-critical">
                Failing metrics: {failedGate.metrics_failed.join(", ")}
              </p>
            )}
          </div>
        </section>

        {candidate.decision.uncertainties.length > 0 && (
          <section>
            <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-warning">
              Remaining uncertainty
            </h3>
            <ul className="space-y-1">
              {candidate.decision.uncertainties.map((item, i) => (
                <li key={i} className="text-[12.5px] leading-relaxed text-ink-2">
                  • {item}
                </li>
              ))}
            </ul>
          </section>
        )}

        {candidate.decision.reversal_conditions.length > 0 && (
          <section>
            <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-s1">
              What would reverse this decision
            </h3>
            <ul className="space-y-1">
              {candidate.decision.reversal_conditions.map((item, i) => (
                <li key={i} className="text-[12.5px] leading-relaxed text-ink-2">
                  • {item}
                </li>
              ))}
            </ul>
          </section>
        )}

        {nextStep && (
          <section className="rounded-md border border-good/35 bg-good/8 p-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-good">
              Suggested wet-lab next step
            </h3>
            <p className="mt-1 text-[12.5px] leading-relaxed text-ink-2">{nextStep}</p>
          </section>
        )}

        <section>
          <div className="mb-1 flex items-center gap-2">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-ink-2">
              Raw metrics
            </h3>
            <PredictionBadge />
          </div>
          {GATE_ORDER.map((name) => {
            const tests = candidate.tests.filter((t) => t.gate === name);
            if (tests.length === 0) return null;
            return (
              <div key={name} className="mb-3 rounded-md border border-hair bg-surface px-3 py-1">
                <div className="border-b border-hair py-2 text-[11px] font-semibold uppercase tracking-wider text-ink-3">
                  {GATE_LABEL[name]}
                </div>
                {tests.map((test) => (
                  <MetricRow key={test.id} test={test} />
                ))}
              </div>
            );
          })}
        </section>

        <section>
          <h3 className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-2">
            Sequence ({candidate.sequence.length} aa)
          </h3>
          <p className="break-all rounded-md border border-hair bg-surface p-3 font-mono text-[11px] leading-relaxed text-ink-2">
            {candidate.sequence}
          </p>
          <p className="mt-1 text-[11px] text-ink-3">
            Synthetic VHH scaffold with authored CDR loops. Not a real therapeutic sequence.
          </p>
        </section>
      </div>
    </aside>
  );
}

export function StatusPill({ status }: { status: Candidate["status"] }) {
  const map = {
    recommended: { cls: "bg-good/18 text-good border-good/40", label: "recommended" },
    survives: { cls: "bg-s1/15 text-s1 border-s1/40", label: "advanced" },
    rejected: { cls: "bg-critical/18 text-critical border-critical/40", label: "rejected" },
    active: { cls: "bg-surface-3 text-ink-3 border-rule", label: "in progress" },
  }[status];
  return (
    <span
      className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${map.cls}`}
    >
      {map.label}
    </span>
  );
}

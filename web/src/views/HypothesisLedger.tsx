import { Card, Empty } from "../components/primitives";
import type { Hypothesis, Investigation } from "../types";

const STATUS: Record<Hypothesis["status"], { cls: string; label: string }> = {
  proposed: { cls: "border-rule bg-surface-3 text-ink-3", label: "proposed" },
  testing: { cls: "border-s1/45 bg-s1/12 text-s1", label: "testing" },
  survives: { cls: "border-good/45 bg-good/12 text-good", label: "survives" },
  rejected: { cls: "border-critical/45 bg-critical/12 text-critical", label: "rejected" },
  uncertain: { cls: "border-warning/45 bg-warning/12 text-warning", label: "uncertain" },
};

export function HypothesisLedger({ investigation }: { investigation: Investigation }) {
  if (investigation.hypotheses.length === 0) {
    return <Empty>No hypotheses yet. They are created after evidence gathering.</Empty>;
  }

  return (
    <div className="space-y-4">
      <Card className="border-s1/30 bg-s1/6 p-4">
        <p className="text-[13px] leading-relaxed text-ink-2">
          Each hypothesis states in advance what result would kill it. That list is set by the
          engine before any gate runs and is not editable afterwards, so a hypothesis cannot be
          quietly redefined to fit the outcome. This view shows structured rationales — statement,
          evidence, planned test, result, confidence change — not model reasoning traces.
        </p>
      </Card>

      {investigation.hypotheses.map((hypothesis) => (
        <HypothesisCard
          key={hypothesis.id}
          hypothesis={hypothesis}
          investigation={investigation}
        />
      ))}
    </div>
  );
}

function HypothesisCard({
  hypothesis,
  investigation,
}: {
  hypothesis: Hypothesis;
  investigation: Investigation;
}) {
  const status = STATUS[hypothesis.status];
  const delta = hypothesis.posterior_confidence - hypothesis.prior_confidence;
  const supporting = investigation.evidence.filter((e) =>
    hypothesis.supporting_evidence_ids.includes(e.id),
  );
  const contradicting = investigation.evidence.filter((e) =>
    hypothesis.contradicting_evidence_ids.includes(e.id),
  );

  return (
    <Card className="bf-rise p-4">
      <div className="mb-3 flex flex-wrap items-start gap-3">
        <p className="min-w-0 flex-1 text-[14.5px] font-medium leading-relaxed text-ink">
          {hypothesis.statement}
        </p>
        <span
          className={`shrink-0 rounded border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${status.cls}`}
        >
          {status.label}
        </span>
      </div>

      <div className="mb-3 flex items-center gap-3">
        <ConfidenceBar
          prior={hypothesis.prior_confidence}
          posterior={hypothesis.posterior_confidence}
        />
        <span className="whitespace-nowrap text-[11px] tabular-nums text-ink-3">
          {hypothesis.prior_confidence.toFixed(2)} → {hypothesis.posterior_confidence.toFixed(2)}
          <span
            className={`ml-1.5 font-semibold ${
              delta > 0 ? "text-good" : delta < 0 ? "text-critical" : "text-ink-3"
            }`}
          >
            {delta === 0 ? "no change" : `${delta > 0 ? "+" : ""}${delta.toFixed(2)}`}
          </span>
        </span>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <Block title="Would be falsified by" tone="critical">
          <ul className="space-y-1">
            {hypothesis.falsification_criteria.map((criterion, i) => (
              <li key={i} className="text-[12.5px] leading-relaxed text-ink-2">
                • {criterion}
              </li>
            ))}
          </ul>
        </Block>

        <Block title="Planned tests" tone="info">
          <ul className="space-y-1">
            {hypothesis.planned_tests.map((test, i) => (
              <li key={i} className="text-[12.5px] leading-relaxed text-ink-2">
                • {test}
              </li>
            ))}
          </ul>
        </Block>

        {supporting.length > 0 && (
          <Block title="Supporting evidence" tone="good">
            <ul className="space-y-1">
              {supporting.map((item) => (
                <li key={item.id} className="text-[12px] leading-snug text-ink-2">
                  <span className="font-mono text-[10.5px] text-ink-3">{item.evidence_level}</span>{" "}
                  {item.claim}
                </li>
              ))}
            </ul>
          </Block>
        )}

        {contradicting.length > 0 && (
          <Block title="Contradicting evidence" tone="critical">
            <ul className="space-y-1">
              {contradicting.map((item) => (
                <li key={item.id} className="text-[12px] leading-snug text-ink-2">
                  <span className="font-mono text-[10.5px] text-ink-3">{item.evidence_level}</span>{" "}
                  {item.claim}
                </li>
              ))}
            </ul>
          </Block>
        )}
      </div>

      {hypothesis.result_summary && (
        <div className="mt-3 rounded-md border border-hair bg-surface-2 p-3">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">
            Result
          </div>
          <p className="mt-1 text-[13px] leading-relaxed text-ink-2">
            {hypothesis.result_summary}
          </p>
        </div>
      )}
    </Card>
  );
}

function Block({
  title,
  tone,
  children,
}: {
  title: string;
  tone: "good" | "critical" | "info";
  children: React.ReactNode;
}) {
  const cls = { good: "text-good", critical: "text-critical", info: "text-s1" }[tone];
  return (
    <div>
      <div className={`mb-1 text-[11px] font-semibold uppercase tracking-wider ${cls}`}>
        {title}
      </div>
      {children}
    </div>
  );
}

function ConfidenceBar({ prior, posterior }: { prior: number; posterior: number }) {
  const low = Math.min(prior, posterior) * 100;
  const high = Math.max(prior, posterior) * 100;
  const rose = posterior >= prior;
  return (
    <div className="relative h-2 flex-1 rounded-sm bg-surface-3" title="Confidence before → after">
      <div
        className={`absolute inset-y-0 rounded-sm ${rose ? "bg-good/60" : "bg-critical/60"}`}
        style={{ left: `${low}%`, width: `${Math.max(high - low, 0.8)}%` }}
      />
      <div
        className="absolute inset-y-[-2px] w-px bg-ink-2"
        style={{ left: `${prior * 100}%` }}
        title={`prior ${prior}`}
      />
      <div
        className="absolute inset-y-[-4px] w-[2px] rounded bg-ink"
        style={{ left: `${posterior * 100}%` }}
        title={`posterior ${posterior}`}
      />
    </div>
  );
}

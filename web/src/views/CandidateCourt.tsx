import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api";
import { CandidateDetail, StatusPill } from "../components/CandidateDetail";
import { GateBar, GateLegend } from "../components/GateBar";
import { Button, Card, Empty, PredictionBadge, SectionTitle } from "../components/primitives";
import { GATE_LABEL, GATE_ORDER, type Candidate, type Investigation } from "../types";

const RAMP = ["#b7d3f6", "#86b6ef", "#5598e7", "#2a78d6", "#184f95"];

function funnelData(investigation: Investigation) {
  const total = investigation.candidates.length;
  const rejectedAt = (gate: string) =>
    investigation.candidates.filter((c) =>
      c.gates.some((g) => g.gate === gate && !g.passed),
    ).length;

  let remaining = total;
  const rows = [{ stage: "Generated", remaining: total, rejected: 0 }];
  for (const gate of GATE_ORDER) {
    const lost = rejectedAt(gate);
    remaining -= lost;
    rows.push({ stage: GATE_LABEL[gate], remaining, rejected: lost });
  }
  return rows;
}

export function CandidateCourt({
  investigation,
  flashed,
  onAction,
}: {
  investigation: Investigation;
  flashed: Set<string>;
  onAction: (message: string) => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "surviving" | "rejected">("all");
  const [busy, setBusy] = useState(false);

  const candidates = useMemo(() => {
    const sorted = [...investigation.candidates].sort((a, b) => {
      const rank = (c: Candidate) =>
        c.status === "recommended" ? 0 : c.status === "survives" ? 1 : c.status === "active" ? 2 : 3;
      return rank(a) - rank(b) || a.id.localeCompare(b.id);
    });
    if (filter === "surviving")
      return sorted.filter((c) => c.status === "recommended" || c.status === "survives");
    if (filter === "rejected") return sorted.filter((c) => c.status === "rejected");
    return sorted;
  }, [investigation.candidates, filter]);

  const funnel = useMemo(() => funnelData(investigation), [investigation]);
  const surviving = investigation.candidates.filter(
    (c) => c.status === "survives" || c.status === "recommended",
  ).length;
  const readyToChallenge =
    !investigation.challenge_run && investigation.status === "INDEPENDENT_VALIDATION";
  const readyToRedesign = investigation.challenge_run && !investigation.redesign_run;

  const run = async (fn: () => Promise<unknown>, message: string) => {
    setBusy(true);
    try {
      await fn();
      onAction(message);
    } catch (err) {
      onAction(`Failed: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const selectedCandidate = candidates.find((c) => c.id === selected)
    ?? investigation.candidates.find((c) => c.id === selected);

  return (
    <div className="space-y-5">
      {/* Action bar — the two moments the demo is built around. */}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-hair bg-surface px-4 py-3">
        <div className="mr-auto">
          <div className="text-sm font-semibold">
            {surviving} surviving · {investigation.candidates.length - surviving} rejected
          </div>
          <div className="text-xs text-ink-3">{investigation.status_detail}</div>
        </div>

        <Button
          variant={readyToChallenge ? "danger" : "default"}
          disabled={!readyToChallenge || busy}
          onClick={() => run(() => api.challenge(investigation.id), "Adversarial challenge started.")}
          title={
            readyToChallenge
              ? "Run the alanine scan and decoy panel against every surviving candidate."
              : investigation.challenge_run
                ? "The challenge has already run for this investigation."
                : "Available once independent validation completes."
          }
          className={readyToChallenge ? "relative overflow-hidden bf-sweep" : ""}
        >
          ⚔ Challenge Survivors
        </Button>

        <Button
          variant={readyToRedesign ? "primary" : "default"}
          disabled={!readyToRedesign || busy}
          onClick={() => run(() => api.redesign(investigation.id), "Redesigning the near-miss.")}
          title={
            readyToRedesign
              ? "Redesign the rejected candidate that missed by the smallest margin, then re-run all four gates on it."
              : investigation.redesign_run
                ? "This MVP permits one redesign iteration and it has been used."
                : "Available after the challenge."
          }
        >
          ⟳ Redesign near-miss
        </Button>

        {investigation.challenge_run &&
          investigation.redesign_run &&
          investigation.status !== "COMPLETED" && (
            <Button
              onClick={() => run(() => api.finalize(investigation.id), "Building the dossier.")}
              disabled={busy}
            >
              Finalise dossier
            </Button>
          )}
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
        <div>
          <SectionTitle hint={`${candidates.length} shown`}>Candidate Court</SectionTitle>

          <div className="mb-3 flex flex-wrap items-center gap-2">
            {(["all", "surviving", "rejected"] as const).map((key) => (
              <button
                key={key}
                onClick={() => setFilter(key)}
                className={`rounded-md border px-2.5 py-1 text-xs capitalize transition ${
                  filter === key
                    ? "border-s1 bg-s1/15 text-s1"
                    : "border-rule bg-surface-2 text-ink-3 hover:text-ink"
                }`}
              >
                {key}
              </button>
            ))}
            <span className="ml-auto">
              <PredictionBadge />
            </span>
          </div>

          {candidates.length === 0 ? (
            <Empty>No candidates yet. Start the investigation from Mission Control.</Empty>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {candidates.map((candidate) => (
                <CandidateCard
                  key={candidate.id}
                  candidate={candidate}
                  flash={flashed.has(candidate.id)}
                  onClick={() => setSelected(candidate.id)}
                />
              ))}
            </div>
          )}

          <div className="mt-4 rounded-md border border-hair bg-surface px-4 py-3">
            <GateLegend />
          </div>
        </div>

        <div className="space-y-4">
          <Card className="p-4">
            <SectionTitle hint="candidates remaining">Gate funnel</SectionTitle>
            <div className="h-[240px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={funnel}
                  layout="vertical"
                  margin={{ top: 4, right: 34, bottom: 4, left: 4 }}
                  barCategoryGap={6}
                >
                  <XAxis type="number" hide domain={[0, investigation.candidates.length || 1]} />
                  <YAxis
                    type="category"
                    dataKey="stage"
                    width={116}
                    tickLine={false}
                    axisLine={false}
                    tick={{ fill: "#898781", fontSize: 11 }}
                  />
                  <Tooltip
                    cursor={{ fill: "rgba(255,255,255,0.04)" }}
                    contentStyle={{
                      background: "#1b1b18",
                      border: "1px solid #383835",
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                    labelStyle={{ color: "#ffffff" }}
                    itemStyle={{ color: "#c3c2b7" }}
                    formatter={(value: number, _name, item) => [
                      `${value} remaining · ${item.payload.rejected} rejected here`,
                      item.payload.stage,
                    ]}
                  />
                  <Bar dataKey="remaining" radius={[0, 4, 4, 0]} isAnimationActive={false}>
                    {funnel.map((_, index) => (
                      <Cell key={index} fill={RAMP[Math.min(index, RAMP.length - 1)]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className="mt-1 text-[11px] leading-snug text-ink-3">
              Each stage shows how many candidates were still alive after that gate. Hover for the
              number rejected at each one.
            </p>
          </Card>

          <Card className="p-4">
            <SectionTitle>Rejection reasons</SectionTitle>
            <div className="space-y-2">
              {GATE_ORDER.map((gate, i) => {
                const rejected = investigation.candidates.filter((c) =>
                  c.gates.some((g) => g.gate === gate && !g.passed),
                );
                if (rejected.length === 0) return null;
                return (
                  <div key={gate} className="text-xs">
                    <div className="flex items-center gap-2">
                      <span
                        className="h-2.5 w-2.5 shrink-0 rounded-sm"
                        style={{ background: ["#3987e5", "#d95926", "#199e70", "#c98500"][i] }}
                        aria-hidden
                      />
                      <span className="text-ink-2">{GATE_LABEL[gate]}</span>
                      <span className="ml-auto font-semibold tabular-nums text-ink">
                        {rejected.length}
                      </span>
                    </div>
                    <div className="ml-[18px] mt-0.5 font-mono text-[10.5px] text-ink-3">
                      {rejected.map((c) => c.id).join(", ")}
                    </div>
                  </div>
                );
              })}
              {investigation.candidates.every((c) => c.status !== "rejected") && (
                <p className="text-xs text-ink-3">No rejections yet.</p>
              )}
            </div>
          </Card>
        </div>
      </div>

      {selectedCandidate && (
        <CandidateDetail
          candidate={selectedCandidate}
          investigation={investigation}
          onClose={() => setSelected(null)}
          onSelect={setSelected}
        />
      )}
    </div>
  );
}

function CandidateCard({
  candidate,
  flash,
  onClick,
}: {
  candidate: Candidate;
  flash: boolean;
  onClick: () => void;
}) {
  const rejected = candidate.status === "rejected";
  const failedGate = candidate.gates.find((g) => !g.passed);
  const binding = candidate.tests.find((t) => t.metric === "interface_confidence");

  return (
    <button
      onClick={onClick}
      className={`bf-rise group relative w-full overflow-hidden rounded-lg border bg-surface p-3 text-left transition ${
        rejected
          ? "bf-rejected border-critical/35"
          : candidate.status === "recommended"
            ? "border-good/50 shadow-[0_0_0_1px_rgba(12,163,12,0.18)]"
            : "border-hair hover:border-rule"
      } ${flash ? "ring-2 ring-s1" : ""}`}
    >
      {candidate.parent_id && (
        <span className="absolute right-0 top-0 rounded-bl bg-s7/25 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-s7">
          redesign
        </span>
      )}
      <div className="flex items-center gap-2">
        <span className="font-mono text-sm font-semibold">{candidate.id}</span>
        {candidate.rank && (
          <span className="rounded bg-s1/15 px-1 text-[10px] font-bold text-s1">
            #{candidate.rank}
          </span>
        )}
        <span className="ml-auto">
          <StatusPill status={candidate.status} />
        </span>
      </div>

      <div className="mt-2.5">
        <GateBar gates={candidate.gates} size="sm" />
      </div>

      <div className="mt-2 flex items-baseline justify-between text-[11px]">
        <span className="text-ink-3">
          binding{" "}
          <span className="font-semibold tabular-nums text-ink-2">
            {binding ? binding.value : "—"}
          </span>
        </span>
        {candidate.rank_score !== null && (
          <span className="text-ink-3">
            score <span className="font-semibold tabular-nums text-ink-2">{candidate.rank_score}</span>
          </span>
        )}
      </div>

      {rejected && failedGate && (
        <div className="mt-2 border-t border-critical/25 pt-2">
          <div className="text-[10px] font-bold uppercase tracking-wider text-critical">
            ✕ failed {GATE_LABEL[failedGate.gate]}
          </div>
          <div className="mt-0.5 font-mono text-[10.5px] text-ink-3">
            {failedGate.metrics_failed.join(", ")}
          </div>
        </div>
      )}

      {!rejected && candidate.status !== "active" && (
        <div className="mt-2 border-t border-hair pt-2 text-[10.5px] text-ink-3">
          passed {candidate.gates.filter((g) => g.passed).length}/4 gates
        </div>
      )}
    </button>
  );
}

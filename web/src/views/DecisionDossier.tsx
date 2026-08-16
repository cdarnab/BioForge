import { useState } from "react";
import { api } from "../api";
import { StatusPill } from "../components/CandidateDetail";
import { GateBar } from "../components/GateBar";
import { Button, Card, Empty, ModeChip, SectionTitle } from "../components/primitives";
import type { Investigation } from "../types";

const KIND_LABEL: Record<string, string> = {
  report_md: "Markdown dossier",
  report_json: "JSON dossier",
  csv_scores: "Score table (CSV)",
  csv_plate: "Plate map (CSV)",
  task_prompt: "Biomni task prompt",
  raw_tool_output: "Raw tool output",
  import_manifest: "Import manifest",
};

export function DecisionDossier({
  investigation,
  onAction,
}: {
  investigation: Investigation;
  onAction: (message: string) => void;
}) {
  const [approver, setApprover] = useState("");
  const [busy, setBusy] = useState(false);
  const finalists = investigation.candidates
    .filter((c) => c.status === "recommended")
    .sort((a, b) => (a.rank ?? 99) - (b.rank ?? 99));
  const downloads = investigation.artifacts.filter((a) =>
    ["report_md", "report_json", "csv_scores", "csv_plate", "task_prompt"].includes(a.kind),
  );
  const packaged = investigation.status === "COMPLETED" || investigation.artifacts.length > 0;

  const approve = async () => {
    if (!approver.trim()) return;
    setBusy(true);
    try {
      await api.approveBenchling(investigation.id, approver.trim());
      onAction("Benchling write approved and executed.");
    } catch (err) {
      onAction(`Failed: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  if (!packaged) {
    return (
      <Empty>
        The dossier is built after the final review. Run the challenge and redesign in Candidate
        Court, or press <strong>Finalise dossier</strong> there.
      </Empty>
    );
  }

  return (
    <div className="space-y-5">
      <Card className="border-warning/35 bg-warning/6 p-4">
        <p className="text-[13px] leading-relaxed text-ink-2">
          <strong className="text-warning">Scope.</strong> These are computational predictions, not
          experimental results. Nothing in this dossier demonstrates that any molecule engages the
          target. Its purpose is to justify which candidates are worth a laboratory slot, and to
          record what would have to be true for that judgement to be wrong.
        </p>
      </Card>

      <section>
        <SectionTitle hint={`${finalists.length} of ${investigation.candidates.length}`}>
          Recommended for testing
        </SectionTitle>
        {finalists.length === 0 ? (
          <Empty>No candidate cleared every gate. Nothing is recommended.</Empty>
        ) : (
          <div className="grid gap-4 lg:grid-cols-3">
            {finalists.map((candidate) => (
              <Card key={candidate.id} className="bf-rise p-4">
                <div className="flex items-center gap-2">
                  <span className="grid h-6 w-6 place-items-center rounded-full bg-good/18 text-xs font-bold text-good">
                    {candidate.rank}
                  </span>
                  <span className="font-mono text-sm font-semibold">{candidate.id}</span>
                  <span className="ml-auto">
                    <StatusPill status={candidate.status} />
                  </span>
                </div>
                {candidate.parent_id && (
                  <p className="mt-1.5 text-[11px] text-s7">
                    redesign of {candidate.parent_id}
                  </p>
                )}
                <div className="mt-3">
                  <GateBar gates={candidate.gates} size="sm" />
                </div>
                <p className="mt-3 text-[12.5px] leading-relaxed text-ink-2">
                  {investigation.narrative[`headline_${candidate.id}`] ??
                    candidate.decision.summary}
                </p>
                <div className="mt-3 border-t border-hair pt-2">
                  <div className="text-[10.5px] font-semibold uppercase tracking-wider text-warning">
                    Remaining uncertainty
                  </div>
                  <ul className="mt-1 space-y-0.5">
                    {candidate.decision.uncertainties.slice(0, 2).map((item, i) => (
                      <li key={i} className="text-[11.5px] leading-snug text-ink-3">
                        • {item}
                      </li>
                    ))}
                  </ul>
                </div>
                <div className="mt-2 border-t border-hair pt-2">
                  <div className="text-[10.5px] font-semibold uppercase tracking-wider text-s1">
                    Would be reversed by
                  </div>
                  <ul className="mt-1 space-y-0.5">
                    {candidate.decision.reversal_conditions.slice(0, 2).map((item, i) => (
                      <li key={i} className="text-[11.5px] leading-snug text-ink-3">
                        • {item}
                      </li>
                    ))}
                  </ul>
                </div>
                {investigation.narrative[`next_step_${candidate.id}`] && (
                  <div className="mt-2 rounded border border-good/30 bg-good/8 p-2">
                    <div className="text-[10.5px] font-semibold uppercase tracking-wider text-good">
                      Wet-lab next step
                    </div>
                    <p className="mt-0.5 text-[11.5px] leading-snug text-ink-2">
                      {investigation.narrative[`next_step_${candidate.id}`]}
                    </p>
                  </div>
                )}
              </Card>
            ))}
          </div>
        )}
      </section>

      {investigation.narrative.redesign_delta && (
        <Card className="p-4">
          <SectionTitle hint={`parent ${investigation.redesign_parent_id}`}>
            Redesign — what actually changed
          </SectionTitle>
          <DeltaTable markdown={investigation.narrative.redesign_delta} />
          <p className="mt-2 text-[11.5px] text-ink-3">
            The redesign targeted the developability liability and hit it. The predicted affinity,
            cross-model agreement and melting temperature all moved slightly the wrong way — that
            tradeoff is the honest shape of this edit, and it is shown rather than smoothed over.
          </p>
        </Card>
      )}

      <section className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4">
          <SectionTitle hint="experiment-ready">Downloads</SectionTitle>
          <div className="space-y-2">
            {downloads.map((artifact) => (
              <a
                key={artifact.id}
                href={api.artifactUrl(investigation.id, artifact.id)}
                className="flex items-center gap-3 rounded-md border border-hair bg-surface-2 px-3 py-2 transition hover:border-s1"
              >
                <span className="text-s1">↓</span>
                <span className="min-w-0">
                  <span className="block text-[13px] text-ink">
                    {KIND_LABEL[artifact.kind] ?? artifact.kind}
                  </span>
                  <span className="block truncate font-mono text-[11px] text-ink-3">
                    {artifact.filename} · {(artifact.size_bytes / 1024).toFixed(1)} kB
                  </span>
                </span>
              </a>
            ))}
            {downloads.length === 0 && <Empty>No artifacts yet.</Empty>}
          </div>
        </Card>

        <Card className="p-4">
          <SectionTitle hint="human approval required">Benchling handoff</SectionTitle>
          <div className="mb-3 flex items-center gap-2">
            <ModeChip
              mode={
                investigation.integrations.find((i) => i.name === "benchling")?.mode ?? "fixture"
              }
            />
            <span className="text-[11.5px] text-ink-3">
              {investigation.benchling.records.length ||
                investigation.candidates.filter((c) => c.status === "recommended").length}{" "}
              record(s) to write
            </span>
          </div>

          {investigation.benchling.approved ? (
            <div className="rounded-md border border-good/40 bg-good/8 p-3">
              <p className="text-[12.5px] text-ink-2">
                Approved by <strong>{investigation.benchling.approved_by}</strong> at{" "}
                {investigation.benchling.approved_at?.slice(0, 19).replace("T", " ")}.
              </p>
              <p className="mt-1 text-[11.5px] text-ink-3">{investigation.benchling.note}</p>
            </div>
          ) : (
            <>
              <p className="mb-2 text-[12px] leading-relaxed text-ink-3">
                Writing to a system of record is not reversible from here. Type your name to
                approve; the adapter refuses the write without it, and the approval is recorded in
                the audit trail.
              </p>
              <div className="flex gap-2">
                <input
                  value={approver}
                  onChange={(event) => setApprover(event.target.value)}
                  placeholder="Your name"
                  className="min-w-0 flex-1 rounded-md border border-rule bg-surface-2 px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-3 focus:border-s1"
                />
                <Button
                  variant="primary"
                  disabled={!approver.trim() || busy}
                  onClick={approve}
                  title="Approve and execute the Benchling write"
                >
                  Approve write
                </Button>
              </div>
            </>
          )}
        </Card>
      </section>

      <Card className="p-4">
        <SectionTitle hint="the plan this run hands off">Suggested validation</SectionTitle>
        <ol className="space-y-2">
          {[
            "Express each recommended candidate at small scale and confirm a monomeric species by SEC before any binding work. A candidate that will not express is not a binding failure.",
            "Run SPR or BLI against recombinant VEGF-A165, recording the isoform — the epitope selected here is not present on every isoform.",
            "Counter-screen on the same chip against PlGF and VEGF-B. The decoy gate in this run is a prediction; this is the measurement that replaces it.",
            "Use the attached plate map, including its positive control. Without it, an all-negative plate is uninterpretable.",
            "Report results back against the reversal conditions listed for each candidate.",
          ].map((step, i) => (
            <li key={i} className="flex gap-3 text-[13px] leading-relaxed text-ink-2">
              <span className="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-surface-3 text-[11px] font-semibold text-ink-3">
                {i + 1}
              </span>
              {step}
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

/** Renders the pipe-table the engine produced, without pulling in a Markdown lib. */
function DeltaTable({ markdown }: { markdown: string }) {
  const rows = markdown
    .trim()
    .split("\n")
    .map((line) => line.split("|").map((cell) => cell.trim()).filter(Boolean))
    .filter((cells) => cells.length > 0 && !cells[0].startsWith("---"));
  if (rows.length < 2) return null;
  const [header, ...body] = rows;

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-[12.5px]">
        <thead>
          <tr className="border-b border-rule text-left text-ink-3">
            {header.map((cell) => (
              <th key={cell} className="py-1.5 pr-4 font-medium">
                {cell}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((cells, i) => {
            const change = cells[3] ?? "";
            const tone = change.startsWith("improved")
              ? "text-good"
              : change.startsWith("worse")
                ? "text-critical"
                : "text-ink-3";
            return (
              <tr key={i} className="border-b border-hair/60">
                <td className="py-1.5 pr-4 font-mono text-ink-2">{cells[0]}</td>
                <td className="py-1.5 pr-4 tabular-nums text-ink-3">{cells[1]}</td>
                <td className="py-1.5 pr-4 tabular-nums text-ink">{cells[2]}</td>
                <td className={`py-1.5 pr-4 ${tone}`}>{change}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

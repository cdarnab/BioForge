import { useMemo, useState } from "react";
import { Card, Empty, ModeChip, SectionTitle, StatTile } from "../components/primitives";
import type { EvidenceItem, Investigation } from "../types";

const LEVEL_STYLE: Record<
  EvidenceItem["evidence_level"],
  { label: string; cls: string; explain: string }
> = {
  observed: {
    label: "observed",
    cls: "border-good/50 bg-good/12 text-good",
    explain: "Directly measured — e.g. an experimental structure.",
  },
  reported: {
    label: "reported",
    cls: "border-s1/50 bg-s1/12 text-s1",
    explain: "Stated in a paper, regulatory record or trial registry.",
  },
  annotated: {
    label: "annotated",
    cls: "border-s7/50 bg-s7/12 text-s7",
    explain: "A curated database annotation, itself derived from other work.",
  },
  predicted: {
    label: "predicted",
    cls: "border-warning/50 bg-warning/12 text-warning",
    explain: "Model output. Not an observation of anything.",
  },
};

const SOURCE_TYPES = ["paper", "database", "regulatory", "trial", "analysis", "benchling"] as const;

export function EvidenceBoard({ investigation }: { investigation: Investigation }) {
  const [source, setSource] = useState<string>("all");
  const [level, setLevel] = useState<string>("all");

  const items = useMemo(() => {
    return investigation.evidence.filter(
      (item) =>
        (source === "all" || item.source_type === source) &&
        (level === "all" || item.evidence_level === level),
    );
  }, [investigation.evidence, source, level]);

  const contradictions = items.filter((i) => i.support === "contradicts");
  const rest = items.filter((i) => i.support !== "contradicts");
  const counts = {
    observed: investigation.evidence.filter((e) => e.evidence_level === "observed").length,
    annotated: investigation.evidence.filter((e) => e.evidence_level === "annotated").length,
    reported: investigation.evidence.filter((e) => e.evidence_level === "reported").length,
    predicted: investigation.evidence.filter((e) => e.evidence_level === "predicted").length,
  };

  const synthesis = investigation.narrative.evidence;
  const contradiction = investigation.narrative.evidence_contradiction;
  const questions = investigation.narrative.evidence_open_questions;

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile label="Observed" value={counts.observed} sub="measured, e.g. a structure" tone="good" />
        <StatTile label="Database annotations" value={counts.annotated} sub="curated, second-hand" />
        <StatTile label="Reported" value={counts.reported} sub="papers, regulators, trials" />
        <StatTile
          label="Model predictions"
          value={counts.predicted}
          sub="not observations"
          tone="warning"
        />
      </div>

      {synthesis && (
        <Card className="p-4">
          <SectionTitle
            hint={
              investigation.narrative.evidence_mode === "live"
                ? "synthesised by Claude"
                : "deterministic template — no model call"
            }
          >
            Synthesis
          </SectionTitle>
          <p className="text-[13.5px] leading-relaxed text-ink-2">{synthesis}</p>
          {contradiction && (
            <div className="mt-3 rounded-md border border-critical/40 bg-critical/8 p-3">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-critical">
                Most important contradicting evidence
              </div>
              <p className="mt-1 text-[13px] leading-relaxed text-ink-2">{contradiction}</p>
            </div>
          )}
          {questions && (
            <div className="mt-3">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-3">
                Open questions
              </div>
              <ul className="mt-1 space-y-0.5">
                {questions.split("\n").map((q, i) => (
                  <li key={i} className="text-[13px] text-ink-2">
                    • {q}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-ink-3">Source</span>
        <FilterGroup
          options={["all", ...SOURCE_TYPES]}
          value={source}
          onChange={setSource}
        />
        <span className="ml-3 text-xs text-ink-3">Level</span>
        <FilterGroup
          options={["all", "observed", "annotated", "reported", "predicted"]}
          value={level}
          onChange={setLevel}
        />
      </div>

      {contradictions.length > 0 && (
        <section>
          <SectionTitle hint="shown first, always">Contradicting evidence</SectionTitle>
          <div className="grid gap-3 md:grid-cols-2">
            {contradictions.map((item) => (
              <EvidenceCard key={item.id} item={item} />
            ))}
          </div>
        </section>
      )}

      <section>
        <SectionTitle hint={`${rest.length} items`}>Supporting and contextual</SectionTitle>
        {rest.length === 0 ? (
          <Empty>No evidence matches these filters.</Empty>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            {rest.map((item) => (
              <EvidenceCard key={item.id} item={item} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function FilterGroup({
  options,
  value,
  onChange,
}: {
  options: readonly string[];
  value: string;
  onChange: (next: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1">
      {options.map((option) => (
        <button
          key={option}
          onClick={() => onChange(option)}
          className={`rounded border px-2 py-0.5 text-[11px] capitalize transition ${
            value === option
              ? "border-s1 bg-s1/15 text-s1"
              : "border-rule bg-surface-2 text-ink-3 hover:text-ink"
          }`}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

function EvidenceCard({ item }: { item: EvidenceItem }) {
  const level = LEVEL_STYLE[item.evidence_level];
  const contradicts = item.support === "contradicts";
  return (
    <article
      className={`bf-rise rounded-lg border p-3.5 ${
        contradicts ? "border-critical/40 bg-critical/6" : "border-hair bg-surface"
      }`}
    >
      <div className="mb-2 flex flex-wrap items-center gap-1.5">
        <span
          title={level.explain}
          className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${level.cls}`}
        >
          {level.label}
        </span>
        {contradicts && (
          <span className="rounded border border-critical/50 bg-critical/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-critical">
            ⚠ contradicts
          </span>
        )}
        {item.support === "supports" && (
          <span className="rounded border border-good/40 bg-good/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-good">
            supports
          </span>
        )}
        <span className="rounded bg-surface-3 px-1.5 py-0.5 text-[10px] text-ink-3">
          {item.source_type}
        </span>
        <span className="ml-auto">
          <ModeChip mode={item.provenance.mode} />
        </span>
      </div>

      <p className="text-[13.5px] leading-relaxed text-ink">{item.claim}</p>

      <div className="mt-2.5 border-t border-hair pt-2 text-[11px] text-ink-3">
        {item.source_url ? (
          <a
            href={item.source_url}
            target="_blank"
            rel="noreferrer noopener"
            className="text-s1 underline underline-offset-2 hover:brightness-125"
          >
            {item.source_title}
          </a>
        ) : (
          <span>{item.source_title}</span>
        )}
        {item.citation_locator && <span> — {item.citation_locator}</span>}
        <div className="mt-1 flex gap-3 tabular-nums">
          <span>relevance {item.relevance}</span>
          <span>confidence {item.confidence}</span>
        </div>
      </div>
    </article>
  );
}

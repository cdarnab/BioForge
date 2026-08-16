import type { ReactNode } from "react";
import type { AdapterMode, Provenance } from "../types";

export function Card({
  children,
  className = "",
  onClick,
}: {
  children: ReactNode;
  className?: string;
  onClick?: () => void;
}) {
  return (
    <div
      onClick={onClick}
      className={`rounded-lg border border-hair bg-surface ${
        onClick ? "cursor-pointer hover:border-rule" : ""
      } ${className}`}
    >
      {children}
    </div>
  );
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: string }) {
  return (
    <div className="mb-3 flex items-baseline justify-between gap-4">
      <h2 className="text-[13px] font-semibold uppercase tracking-[0.14em] text-ink-2">
        {children}
      </h2>
      {hint && <span className="text-xs text-ink-3">{hint}</span>}
    </div>
  );
}

/** The single most important label in the product. */
export function PredictionBadge({ compact = false }: { compact?: boolean }) {
  return (
    <span
      title="Computational prediction. No experimental measurement exists for this value."
      className="inline-flex shrink-0 items-center gap-1 rounded border border-warning/45 bg-warning/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-warning"
    >
      <svg width="9" height="9" viewBox="0 0 10 10" aria-hidden="true">
        <path d="M5 0 10 9H0z" fill="currentColor" />
      </svg>
      {compact ? "pred" : "prediction"}
    </span>
  );
}

const MODE_STYLE: Record<AdapterMode, { label: string; cls: string; title: string }> = {
  live: {
    label: "live",
    cls: "border-good/50 bg-good/12 text-good",
    title: "Produced by a live call to the integration.",
  },
  fixture: {
    label: "fixture",
    cls: "border-warning/45 bg-warning/10 text-warning",
    title: "Deterministic fixture data. No live service was called.",
  },
  import_handoff: {
    label: "import",
    cls: "border-s7/50 bg-s7/12 text-s7",
    title: "Supplied by a human via the documented import handoff.",
  },
  unavailable: {
    label: "unavailable",
    cls: "border-critical/50 bg-critical/12 text-critical",
    title: "Integration unavailable.",
  },
};

export function ModeChip({ mode, className = "" }: { mode: AdapterMode; className?: string }) {
  const style = MODE_STYLE[mode] ?? MODE_STYLE.unavailable;
  return (
    <span
      title={style.title}
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide ${style.cls} ${className}`}
    >
      {style.label}
    </span>
  );
}

export function ProvenanceLine({ provenance }: { provenance: Provenance }) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ink-3">
      <ModeChip mode={provenance.mode} />
      <span className="font-mono">{provenance.tool}</span>
      {provenance.model_version !== "n/a" && (
        <>
          <span aria-hidden>·</span>
          <span className="font-mono">{provenance.model_version}</span>
        </>
      )}
      {provenance.random_seed !== null && (
        <>
          <span aria-hidden>·</span>
          <span>seed {provenance.random_seed}</span>
        </>
      )}
      {provenance.note && <span className="w-full text-ink-3/85">{provenance.note}</span>}
    </div>
  );
}

const STATUS_TONE = {
  good: "text-good",
  warning: "text-warning",
  critical: "text-critical",
  neutral: "text-ink",
  info: "text-s1",
} as const;

export function StatTile({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  sub?: string;
  tone?: keyof typeof STATUS_TONE;
}) {
  return (
    <div className="rounded-lg border border-hair bg-surface px-4 py-3">
      <div className="text-[11px] uppercase tracking-[0.12em] text-ink-3">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${STATUS_TONE[tone]}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[11px] leading-snug text-ink-3">{sub}</div>}
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "default",
  disabled = false,
  title,
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "default" | "primary" | "danger" | "ghost";
  disabled?: boolean;
  title?: string;
  className?: string;
}) {
  const styles = {
    default: "border-rule bg-surface-2 text-ink hover:bg-surface-3",
    primary: "border-s1 bg-s1 text-white hover:brightness-110",
    danger: "border-critical bg-critical text-white hover:brightness-110",
    ghost: "border-transparent bg-transparent text-ink-2 hover:text-ink hover:bg-surface-2",
  }[variant];
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex items-center justify-center gap-2 rounded-md border px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${styles} ${className}`}
    >
      {children}
    </button>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-rule bg-surface/50 px-6 py-10 text-center text-sm text-ink-3">
      {children}
    </div>
  );
}

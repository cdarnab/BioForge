import { GATE_LABEL, GATE_ORDER, type GateOutcome } from "../types";

/**
 * Four segments, one per gate. A gate that has not run is a flat rule; a pass is
 * green; a fail is red and also carries a slash mark so the state is not
 * conveyed by colour alone.
 */
export function GateBar({
  gates,
  size = "md",
}: {
  gates: GateOutcome[];
  size?: "sm" | "md";
}) {
  const height = size === "sm" ? "h-1.5" : "h-2";
  return (
    <div className="flex gap-1" role="list" aria-label="Gate outcomes">
      {GATE_ORDER.map((name) => {
        const outcome = gates.find((g) => g.gate === name);
        const state = !outcome ? "pending" : outcome.passed ? "pass" : "fail";
        const cls =
          state === "pass"
            ? "bg-good"
            : state === "fail"
              ? "bg-critical"
              : "bg-rule";
        const title = outcome
          ? `${GATE_LABEL[name]}: ${outcome.passed ? "pass" : "FAIL"} — ${outcome.reason}`
          : `${GATE_LABEL[name]}: not run yet`;
        return (
          <div
            key={name}
            role="listitem"
            title={title}
            aria-label={title}
            className={`relative flex-1 overflow-hidden rounded-sm ${height} ${cls}`}
          >
            {state === "fail" && (
              <span
                aria-hidden
                className="absolute inset-0 opacity-70"
                style={{
                  backgroundImage:
                    "repeating-linear-gradient(45deg, transparent 0 3px, rgba(0,0,0,0.55) 3px 6px)",
                }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

export function GateLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-ink-3">
      {GATE_ORDER.map((name, i) => (
        <span key={name} className="inline-flex items-center gap-1.5">
          <span className="grid h-4 w-4 place-items-center rounded-sm border border-rule text-[9px]">
            {i + 1}
          </span>
          {GATE_LABEL[name]}
        </span>
      ))}
      <span className="ml-auto inline-flex items-center gap-3">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-sm bg-good" /> pass
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span
            className="h-2 w-4 rounded-sm bg-critical"
            style={{
              backgroundImage:
                "repeating-linear-gradient(45deg, transparent 0 3px, rgba(0,0,0,0.55) 3px 6px)",
            }}
          />{" "}
          fail
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-4 rounded-sm bg-rule" /> not run
        </span>
      </span>
    </div>
  );
}

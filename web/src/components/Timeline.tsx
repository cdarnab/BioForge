const STEPS = [
  { key: "CREATED", label: "Created" },
  { key: "EVIDENCE_GATHERING", label: "Evidence" },
  { key: "HYPOTHESES_CREATED", label: "Hypotheses" },
  { key: "CANDIDATES_READY", label: "Candidates" },
  { key: "PRIMARY_TESTING", label: "Binding" },
  { key: "INDEPENDENT_VALIDATION", label: "Independent" },
  { key: "ADVERSARIAL_CHALLENGE", label: "Challenge" },
  { key: "REDESIGNING", label: "Redesign" },
  { key: "FINAL_REVIEW", label: "Review" },
  { key: "PACKAGE_CREATED", label: "Package" },
  { key: "COMPLETED", label: "Done" },
];

export function Timeline({ status, detail }: { status: string; detail?: string }) {
  const failed = status === "FAILED";
  const review = status === "NEEDS_REVIEW";
  const index = STEPS.findIndex((s) => s.key === status);

  return (
    <div className="border-b border-hair bg-surface/70 px-6 py-3">
      <ol className="flex items-center gap-0 overflow-x-auto">
        {STEPS.map((step, i) => {
          const done = index > i;
          const active = index === i;
          const tone = failed
            ? "border-critical text-critical"
            : done
              ? "border-good/70 text-good"
              : active
                ? "border-s1 text-s1"
                : "border-rule text-ink-3";
          return (
            <li key={step.key} className="flex shrink-0 items-center">
              <div className="flex items-center gap-2">
                <span
                  className={`grid h-5 w-5 place-items-center rounded-full border text-[10px] font-semibold ${tone} ${
                    active && !failed ? "bf-pulse" : ""
                  }`}
                  aria-current={active ? "step" : undefined}
                >
                  {done ? "✓" : i + 1}
                </span>
                <span
                  className={`whitespace-nowrap text-xs ${
                    active ? "font-semibold text-ink" : done ? "text-ink-2" : "text-ink-3"
                  }`}
                >
                  {step.label}
                </span>
              </div>
              {i < STEPS.length - 1 && (
                <span
                  className={`mx-2.5 h-px w-7 ${done ? "bg-good/50" : "bg-rule"}`}
                  aria-hidden
                />
              )}
            </li>
          );
        })}
      </ol>
      {(detail || failed || review) && (
        <p
          className={`mt-2 text-xs ${
            failed ? "text-critical" : review ? "text-warning" : "text-ink-3"
          }`}
        >
          {failed && "Run failed: "}
          {review && "Needs review: "}
          {detail}
        </p>
      )}
    </div>
  );
}

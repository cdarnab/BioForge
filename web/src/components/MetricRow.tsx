import { METRIC_KIND, METRIC_KIND_LABEL, type TestResult } from "../types";
import { ModeChip } from "./primitives";

function ruleText(test: TestResult): string {
  if (test.direction === "informational") return "no threshold";
  if (test.direction === "in_range")
    return `${test.threshold ?? "?"} to ${test.threshold_high ?? "?"}`;
  const comparator = test.direction === "higher_is_better" ? "≥" : "≤";
  return `${comparator} ${test.threshold}`;
}

/**
 * Position of the value on a 0-100 track relative to its threshold, so the
 * distance from the boundary is visible rather than something you compute in
 * your head. The scale is local to the metric, so it is decorative context for
 * the numbers beside it, not a cross-metric comparison.
 */
function trackPosition(test: TestResult): { value: number; threshold: number } | null {
  if (test.threshold === null || test.direction === "informational") return null;
  const anchor = test.threshold || 1;
  const span = Math.max(Math.abs(anchor) * 1.6, Math.abs(test.value) * 1.25, 1e-6);
  const clamp = (n: number) => Math.min(100, Math.max(0, (n / span) * 100));
  return { value: clamp(Math.abs(test.value)), threshold: clamp(Math.abs(anchor)) };
}

export function MetricRow({ test }: { test: TestResult }) {
  const kind = METRIC_KIND[test.metric] ?? "model_prediction";
  const track = trackPosition(test);
  const verdict =
    test.passed === null ? "info" : test.passed ? "pass" : "FAIL";

  return (
    <div className="border-t border-hair/70 py-2.5 first:border-t-0">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="font-mono text-[12.5px] text-ink">{test.metric}</span>
        <span className="text-[12.5px] font-semibold tabular-nums text-ink">
          {test.value}
          {test.unit && <span className="ml-0.5 text-ink-3">{test.unit}</span>}
        </span>
        <span className="text-[11px] text-ink-3">
          {test.uncertainty !== null ? `±${test.uncertainty}` : "uncertainty not reported"}
        </span>
        <span className="ml-auto flex items-center gap-2">
          <span className="text-[11px] text-ink-3">{ruleText(test)}</span>
          <span
            className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
              verdict === "pass"
                ? "bg-good/15 text-good"
                : verdict === "FAIL"
                  ? "bg-critical/18 text-critical"
                  : "bg-surface-3 text-ink-3"
            }`}
          >
            {verdict}
          </span>
        </span>
      </div>

      {track && (
        <div className="relative mt-1.5 h-1.5 rounded-sm bg-surface-3">
          <div
            className={`absolute inset-y-0 left-0 rounded-sm ${
              test.passed ? "bg-good/70" : "bg-critical/70"
            }`}
            style={{ width: `${track.value}%` }}
          />
          <div
            className="absolute inset-y-[-3px] w-px bg-ink-2"
            style={{ left: `${track.threshold}%` }}
            title={`threshold ${test.threshold}`}
          />
        </div>
      )}

      <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ink-3">
        <ModeChip mode={test.provenance.mode} />
        <span className="rounded bg-surface-3 px-1.5 py-0.5">
          {METRIC_KIND_LABEL[kind] ?? kind}
        </span>
        <span className="font-mono">{test.tool}</span>
        <span aria-hidden>·</span>
        <span className="font-mono">{test.model_version}</span>
        {test.artifact_ids.length > 0 && (
          <span className="text-s1">{test.artifact_ids.length} artifact</span>
        )}
      </div>
      {test.rationale && <p className="mt-1 text-[11.5px] text-ink-2">{test.rationale}</p>}
    </div>
  );
}

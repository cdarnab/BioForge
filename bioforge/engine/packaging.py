"""Dossier packaging: Markdown, JSON, CSV score table, CSV plate map.

Everything a downstream reader needs to recompute the verdict is embedded: the
raw metrics, the policy that was applied, the provenance of each number, and the
audit trail. The Markdown opens with the scope statement rather than burying it,
because the single easiest way for this product to mislead someone is for the
report to read like results.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from ..biophysics import METRIC_KIND
from ..models import AuditEvent, Candidate, Investigation
from .decision_policy import Policy, compute_rank_score

SCOPE_STATEMENT = (
    "**Scope: these are computational predictions, not experimental results.** No candidate "
    "in this report has been expressed, purified, or tested for binding. Nothing here "
    "demonstrates that any molecule engages the target. The purpose of this document is to "
    "justify which candidates are worth spending a laboratory slot on, and to record exactly "
    "what would have to be true for that judgement to be wrong."
)

PLATE_ROWS = "ABCDEFGH"
PLATE_COLS = 12


def dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------


def score_table_csv(inv: Investigation) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        [
            "candidate_id",
            "status",
            "rank",
            "rank_score",
            "parent_id",
            "gate",
            "metric",
            "value",
            "unit",
            "threshold",
            "threshold_high",
            "direction",
            "passed",
            "metric_kind",
            "uncertainty",
            "tool",
            "model_version",
            "adapter_mode",
            "provenance_note",
            "rationale",
        ]
    )
    for candidate in sorted(inv.candidates, key=lambda c: c.id):
        for test in candidate.tests:
            writer.writerow(
                [
                    candidate.id,
                    candidate.status,
                    candidate.rank if candidate.rank is not None else "",
                    candidate.rank_score if candidate.rank_score is not None else "",
                    candidate.parent_id or "",
                    test.gate,
                    test.metric,
                    test.value,
                    test.unit,
                    "" if test.threshold is None else test.threshold,
                    "" if test.threshold_high is None else test.threshold_high,
                    test.direction,
                    "" if test.passed is None else test.passed,
                    METRIC_KIND.get(test.metric, "unknown"),
                    "" if test.uncertainty is None else test.uncertainty,
                    test.tool,
                    test.model_version,
                    test.provenance.mode.value,
                    (test.provenance.note or "").replace("\n", " "),
                    test.rationale,
                ]
            )
    return buf.getvalue()


def plate_map_csv(inv: Investigation) -> str:
    """A 96-well layout for the recommended candidates plus controls.

    Each finalist gets a triplicate concentration series; the plate also carries
    a buffer blank and a no-binder control so the experiment can fail informatively.
    """
    finalists = inv.finalists()
    concentrations = [100.0, 25.0, 6.25, 1.5625]
    replicates = 3

    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(
        [
            "well",
            "row",
            "column",
            "content",
            "candidate_id",
            "concentration_nm",
            "replicate",
            "role",
            "notes",
        ]
    )

    assignments: list[tuple[str, str, float | str, int, str, str]] = []
    for candidate in finalists:
        for conc in concentrations:
            for rep in range(1, replicates + 1):
                assignments.append(
                    (
                        candidate.name,
                        candidate.id,
                        conc,
                        rep,
                        "test_article",
                        "Predicted binder; affinity unknown.",
                    )
                )
    for rep in range(1, replicates + 1):
        assignments.append(
            ("buffer_blank", "", "", rep, "negative_control", "Buffer only; defines baseline.")
        )
    for rep in range(1, replicates + 1):
        assignments.append(
            (
                "irrelevant_vhh",
                "",
                100.0,
                rep,
                "negative_control",
                "Unrelated VHH at top concentration; controls for non-specific binding.",
            )
        )
    for rep in range(1, replicates + 1):
        assignments.append(
            (
                "commercial_anti_vegf",
                "",
                100.0,
                rep,
                "positive_control",
                "Commercial anti-VEGF reagent; confirms the antigen is active on this plate.",
            )
        )

    for index, (content, cid, dose, rep, role, notes) in enumerate(assignments):
        if index >= len(PLATE_ROWS) * PLATE_COLS:
            break
        row = PLATE_ROWS[index // PLATE_COLS]
        col = index % PLATE_COLS + 1
        writer.writerow([f"{row}{col}", row, col, content, cid, dose, rep, role, notes])
    return buf.getvalue()


# --------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------


def dossier_json(inv: Investigation, policy: Policy, events: list[AuditEvent]) -> str:
    payload = {
        "scope_statement": SCOPE_STATEMENT.replace("**", ""),
        "investigation": inv.model_dump(mode="json"),
        "decision_policy": policy.as_dict(),
        "ranking_working": {
            c.id: compute_rank_score(policy, c)[1]
            for c in inv.candidates
            if c.status in ("survives", "recommended")
        },
        "audit_trail": [e.model_dump(mode="json") for e in events],
        "reproduction": {
            "seed": inv.seed,
            "policy_version": policy.version,
            "instructions": (
                "Every gate verdict in this file is recomputable: apply decision_policy to "
                "investigation.candidates[].tests. No language model contributed a score."
            ),
        },
    }
    return dumps(payload)


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------


def _metric_row(test) -> str:
    threshold = "—"
    if test.direction == "in_range" and test.threshold is not None:
        threshold = f"{test.threshold:g} to {test.threshold_high:g}"
    elif test.threshold is not None:
        comparator = "≥" if test.direction == "higher_is_better" else "≤"
        threshold = f"{comparator} {test.threshold:g}"
    verdict = "—" if test.passed is None else ("pass" if test.passed else "**FAIL**")
    unc = f"±{test.uncertainty:g}" if test.uncertainty is not None else "not reported"
    return (
        f"| {test.metric} | {test.value:g}{(' ' + test.unit) if test.unit else ''} | {threshold} "
        f"| {verdict} | {unc} | {METRIC_KIND.get(test.metric, 'unknown')} | {test.tool} "
        f"({test.provenance.mode.value}) |"
    )


def _candidate_section(candidate: Candidate, inv: Investigation) -> str:
    lines: list[str] = []
    headline = inv.narrative.get(f"headline_{candidate.id}", "")
    lines.append(f"### {candidate.name}" + (f" — rank {candidate.rank}" if candidate.rank else ""))
    if headline:
        lines.append(f"\n_{headline}_\n")
    if candidate.parent_id:
        lines.append(f"Redesign of **{candidate.parent_id}**. {candidate.generation_note}\n")
    lines.append(f"- Status: **{candidate.status}** ({candidate.decision.outcome})")
    lines.append(f"- Reason codes: `{', '.join(candidate.decision.reason_codes) or 'none'}`")
    if candidate.rank_score is not None:
        lines.append(f"- Ranking score: {candidate.rank_score:g} (see policy for the formula)")
    lines.append(f"- Sequence ({len(candidate.sequence)} aa): `{candidate.sequence}`")
    lines.append("")
    lines.append("| metric | value | threshold | verdict | uncertainty | kind | source |")
    lines.append("|---|---|---|---|---|---|---|")
    for gate in ("binding", "independent_structure", "developability", "robustness"):
        for test in candidate.tests:
            if test.gate == gate:
                lines.append(_metric_row(test))
    lines.append("")
    lines.append(f"**Why:** {candidate.decision.summary}")
    if candidate.decision.uncertainties:
        lines.append("\n**Remaining uncertainty**")
        for item in candidate.decision.uncertainties:
            lines.append(f"- {item}")
    if candidate.decision.reversal_conditions:
        lines.append("\n**What would reverse this decision**")
        for item in candidate.decision.reversal_conditions:
            lines.append(f"- {item}")
    next_step = inv.narrative.get(f"next_step_{candidate.id}")
    if next_step:
        lines.append(f"\n**Suggested wet-lab next step:** {next_step}")
    lines.append("")
    return "\n".join(lines)


def render_redesign_delta(parent: Candidate, child: Candidate) -> str:
    lines = [
        f"| metric | {parent.id} | {child.id} | change |",
        "|---|---|---|---|",
    ]
    child_metrics = {t.metric: t for t in child.tests}
    for test in parent.tests:
        other = child_metrics.get(test.metric)
        if other is None:
            continue
        delta = other.value - test.value
        if abs(delta) < 1e-9:
            arrow = "unchanged"
        elif test.direction == "higher_is_better":
            arrow = f"{'improved' if delta > 0 else 'worse'} ({delta:+g})"
        elif test.direction == "lower_is_better":
            arrow = f"{'improved' if delta < 0 else 'worse'} ({delta:+g})"
        else:
            # in_range and informational metrics have no better/worse direction;
            # labelling them either way would be an unjustified claim.
            arrow = f"changed ({delta:+g})"
        lines.append(f"| {test.metric} | {test.value:g} | {other.value:g} | {arrow} |")
    return "\n".join(lines)


def dossier_markdown(inv: Investigation, policy: Policy, events: list[AuditEvent]) -> str:
    finalists = inv.finalists()
    rejected = [c for c in inv.candidates if c.status == "rejected"]
    out: list[str] = []

    out.append("# BioForge Judge — Decision Dossier\n")
    out.append(f"**Run:** `{inv.id}`  ")
    out.append(
        f"**Target:** {inv.target.name}"
        + (f" (UniProt {inv.target.uniprot_id})" if inv.target.uniprot_id else "")
        + "  "
    )
    out.append(f"**Epitope:** {inv.target.epitope_description}  ")
    out.append(f"**Format:** {inv.target_product_profile.format}  ")
    out.append(f"**Run mode:** {inv.mode}  ")
    out.append(f"**Seed:** {inv.seed}  ")
    out.append(f"**Decision policy:** `{policy.version}` — {policy.label}  ")
    out.append(f"**Generated:** {inv.updated_at}\n")
    out.append(f"> {SCOPE_STATEMENT}\n")

    out.append("## Integration modes for this run\n")
    out.append("| integration | mode | detail |")
    out.append("|---|---|---|")
    for status in inv.integrations:
        out.append(f"| {status.name} | **{status.mode.value}** | {status.detail} |")
    out.append("")

    out.append("## Recommendation\n")
    if not finalists:
        out.append("No candidate cleared every gate. Nothing is recommended for testing.\n")
    else:
        out.append(
            f"{len(finalists)} of {len(inv.candidates)} candidates are recommended for "
            "laboratory testing.\n"
        )
        out.append("| rank | candidate | ranking score | origin |")
        out.append("|---|---|---|---|")
        for candidate in finalists:
            origin = f"redesign of {candidate.parent_id}" if candidate.parent_id else "generated"
            out.append(
                f"| {candidate.rank} | **{candidate.name}** | {candidate.rank_score:g} | {origin} |"
            )
        out.append("")

    out.append("## Evidence summary\n")
    out.append(inv.narrative.get("evidence", "_No synthesis available._") + "\n")
    contradiction = inv.narrative.get("evidence_contradiction")
    if contradiction:
        out.append(f"**Most important contradicting evidence:** {contradiction}\n")
    questions = inv.narrative.get("evidence_open_questions")
    if questions:
        out.append("**Open questions**\n")
        for line in questions.split("\n"):
            out.append(f"- {line}")
        out.append("")

    observed = sum(1 for e in inv.evidence if e.evidence_level == "observed")
    predicted = sum(1 for e in inv.evidence if e.evidence_level == "predicted")
    out.append(
        f"Evidence base: {len(inv.evidence)} items — {observed} observed, "
        f"{sum(1 for e in inv.evidence if e.evidence_level == 'annotated')} database "
        f"annotations, {sum(1 for e in inv.evidence if e.evidence_level == 'reported')} "
        f"reported, {predicted} predicted.\n"
    )
    out.append("| claim | level | support | source |")
    out.append("|---|---|---|---|")
    for item in inv.evidence:
        link = f"[{item.source_title}]({item.source_url})" if item.source_url else item.source_title
        out.append(f"| {item.claim} | {item.evidence_level} | {item.support} | {link} |")
    out.append("")

    out.append("## Hypothesis ledger\n")
    for hypothesis in inv.hypotheses:
        out.append(f"### {hypothesis.statement}\n")
        out.append(
            f"- Status: **{hypothesis.status}** "
            f"(confidence {hypothesis.prior_confidence:g} → {hypothesis.posterior_confidence:g})"
        )
        out.append("- Would be falsified by:")
        for criterion in hypothesis.falsification_criteria:
            out.append(f"  - {criterion}")
        if hypothesis.result_summary:
            out.append(f"- Result: {hypothesis.result_summary}")
        out.append("")

    out.append("## Decision policy applied\n")
    out.append(
        f"_{policy.label}._ Thresholds below are demonstration values unless a source "
        "is cited. Every verdict in this dossier is recomputable from the raw metrics "
        "in the accompanying CSV plus this table.\n"
    )
    out.append("| gate | metric | rule | calibrated? |")
    out.append("|---|---|---|---|")
    for gate in policy.gates:
        for metric in gate.metrics:
            if metric.direction == "informational":
                rule = "informational only"
            elif metric.direction == "higher_is_better":
                rule = f"≥ {metric.minimum:g}"
            elif metric.direction == "lower_is_better":
                rule = f"≤ {metric.maximum:g}"
            else:
                rule = f"{metric.minimum:g} to {metric.maximum:g}"
            out.append(
                f"| {gate.name} | {metric.name} | {rule} | "
                f"{'yes — ' + metric.source if metric.source else '**no**'} |"
            )
    out.append("")

    if finalists:
        out.append("## Recommended candidates\n")
        for candidate in finalists:
            out.append(_candidate_section(candidate, inv))

    advanced = [c for c in inv.candidates if c.status == "survives"]
    if advanced:
        out.append("## Passed every gate but not shortlisted\n")
        for candidate in advanced:
            out.append(_candidate_section(candidate, inv))

    if inv.redesign_parent_id:
        child = next((c for c in inv.candidates if c.parent_id == inv.redesign_parent_id), None)
        if child:
            out.append("## Redesign\n")
            out.append(
                f"{inv.redesign_parent_id} failed one gate by the narrowest margin of any "
                f"rejected candidate and was redesigned as {child.id}.\n"
            )
            out.append(child.generation_note + "\n")
            out.append(inv.narrative.get("redesign_delta", "") + "\n")

    out.append("## Rejected candidates\n")
    out.append("| candidate | rejected at | reason codes | detail |")
    out.append("|---|---|---|---|")
    for candidate in sorted(rejected, key=lambda c: c.id):
        failed = next((g for g in candidate.gates if not g.passed), None)
        out.append(
            f"| {candidate.name} | {failed.gate if failed else '—'} | "
            f"`{', '.join(candidate.decision.reason_codes)}` | {failed.reason if failed else ''} |"
        )
    out.append("")

    out.append("## Suggested validation plan\n")
    out.append(
        "1. Express each recommended candidate at small scale and confirm a monomeric "
        "species by SEC before any binding work. A candidate that will not express is not a "
        "binding failure and should not be recorded as one.\n"
        "2. Run SPR or BLI against recombinant VEGF-A165, with the isoform stated on the "
        "record — the epitope selected here is not present on every isoform.\n"
        "3. Counter-screen on the same chip against PlGF and VEGF-B. The decoy gate in this "
        "run is a prediction; this is the measurement that replaces it.\n"
        "4. Include the plate controls in the attached plate map. Without the positive "
        "control an all-negative plate is uninterpretable.\n"
        "5. Report results back against the reversal conditions listed per candidate.\n"
    )

    out.append("## Audit trail\n")
    out.append("| # | time | state | actor | tool | mode | summary |")
    out.append("|---|---|---|---|---|---|---|")
    for event in events:
        transition = (
            f"{event.prev_state.value if event.prev_state else ''} → {event.next_state.value}"
            if event.next_state
            else ""
        )
        out.append(
            f"| {event.seq} | {event.timestamp} | {transition} | {event.actor} | "
            f"{event.tool or ''} | {event.mode.value if event.mode else ''} | "
            f"{event.summary.replace('|', '/')} |"
        )
    out.append("")

    out.append("## Limitations\n")
    out.append(
        "- Thresholds in the decision policy are uncalibrated demonstration values. They were "
        "chosen to produce an interpretable triage, not from a validated dataset.\n"
        "- Cross-model agreement is not independent evidence. Two structure predictors may "
        "share training data and therefore share failure modes.\n"
        "- Developability heuristics are sequence-scale summaries. They do not model "
        "structure, formulation, or process.\n"
        "- The decoy panel is small and its scores are predictions from the same class of "
        "model that produced the on-target score.\n"
        "- Sequences in the seeded demo are synthetic scaffolds, not real therapeutic "
        "molecules.\n"
        "- See `docs/scientific-limitations.md` for the full treatment.\n"
    )
    return "\n".join(out)


# --------------------------------------------------------------------------


def build_bundle(
    inv: Investigation, policy: Policy, events: list[AuditEvent]
) -> list[tuple[str, str, str, str, str]]:
    """(kind, filename, content, media_type, description) for every artifact."""
    return [
        (
            "report_md",
            f"{inv.id}_dossier.md",
            dossier_markdown(inv, policy, events),
            "text/markdown",
            "Human-readable decision dossier.",
        ),
        (
            "report_json",
            f"{inv.id}_dossier.json",
            dossier_json(inv, policy, events),
            "application/json",
            "Machine-readable dossier including the policy and full audit trail.",
        ),
        (
            "csv_scores",
            f"{inv.id}_scores.csv",
            score_table_csv(inv),
            "text/csv",
            "Every raw metric with its threshold, verdict and provenance.",
        ),
        (
            "csv_plate",
            f"{inv.id}_plate_map.csv",
            plate_map_csv(inv),
            "text/csv",
            "96-well plate map for the recommended candidates plus controls.",
        ),
    ]

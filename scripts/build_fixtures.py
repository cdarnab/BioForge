#!/usr/bin/env python3
"""Generate the seeded VEGF-A candidate fixture.

Sequences are assembled from a shared VHH framework plus per-candidate CDR
loops. The developability metrics that can be computed from a sequence ARE
computed here (see bioforge.biophysics) rather than typed in by hand, so the
redesign step changes real numbers. Model-derived scores (interface confidence,
cross-model agreement, mutation robustness) are authored fixture values — no
model was run to produce them and the fixture adapter says so in its provenance.

Ground-truth control labels are written to a SEPARATE file that the pipeline
never reads. Only the benchmark harness joins them back in, after scoring.

Run:  python scripts/build_fixtures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bioforge.biophysics import CdrSpans, sequence_metrics  # noqa: E402

# A camelid VHH framework scaffold. The hallmark FR2 tetrad (F37/E44/R45/G47
# positions) is present. Framework carries exactly the two conserved cysteines.
FR1 = "QVQLVESGGGLVQAGGSLRLSCAAS"
FR2 = "MGWFRQAPGKEREFVA"
FR3 = "RFTISRDNAKNTVYLQMNSLKPEDTAVYYCAA"
FR4 = "WGQGTQVTVSS"


def assemble(cdr1: str, cdr2: str, cdr3: str) -> tuple[str, CdrSpans]:
    seq = FR1 + cdr1 + FR2 + cdr2 + FR3 + cdr3 + FR4
    a1 = len(FR1)
    b1 = a1 + len(cdr1)
    a2 = b1 + len(FR2)
    b2 = a2 + len(cdr2)
    a3 = b2 + len(FR3)
    b3 = a3 + len(cdr3)
    return seq, CdrSpans(cdr1=(a1, b1), cdr2=(a2, b2), cdr3=(a3, b3))


# --------------------------------------------------------------------------
# Candidate specification
# --------------------------------------------------------------------------
# model_* values are authored fixture numbers attributed to the tool that would
# have produced them in live mode. They are NOT computed from the sequence and
# must never be described as such.

SPEC: list[dict] = [
    {
        "id": "BF-001",
        "cdr": ("GRTFSSYA", "ISWSGGST", "ADRGYSSTWYDY"),
        "note": "Reference-binder surrogate carrying a receptor-blocking-style paratope.",
        "tamarind": {
            "interface_confidence": 0.89,
            "predicted_dg_kcal_mol": -11.4,
            "predicted_tm_celsius": 74.5,
            "immunogenicity_risk": 0.14,
        },
        "modelhub": {"model_agreement": 0.88, "epitope_rmsd_angstrom": 1.2},
        "modal": {"retained_score_across_mutations": 0.83, "decoy_discrimination_margin": 0.41},
    },
    {
        "id": "BF-002",
        "cdr": ("GSTFNSSA", "ITSGGGTT", "ANRDYSGSYPDY"),
        "note": "Loop-grafted variant with a shortened CDR3 apex.",
        "tamarind": {
            "interface_confidence": 0.81,
            "predicted_dg_kcal_mol": -10.2,
            "predicted_tm_celsius": 71.0,
            "immunogenicity_risk": 0.19,
        },
        "modelhub": {"model_agreement": 0.79, "epitope_rmsd_angstrom": 1.8},
        "modal": {"retained_score_across_mutations": 0.74, "decoy_discrimination_margin": 0.32},
    },
    {
        "id": "BF-003",
        "cdr": ("GRTFSNYD", "ISSGGTTN", "ATRDYSNSWTDY"),
        "note": "Design-path pose places CDR3 across the receptor-binding cleft.",
        "tamarind": {
            "interface_confidence": 0.78,
            "predicted_dg_kcal_mol": -9.6,
            "predicted_tm_celsius": 69.2,
            "immunogenicity_risk": 0.22,
        },
        "modelhub": {"model_agreement": 0.52, "epitope_rmsd_angstrom": 5.6},
        "modal": None,
    },
    {
        "id": "BF-004",
        "cdr": ("GRSFSTYS", "INSGGDTT", "AKRDYSTSWNDY"),
        "note": "Charge-complementary paratope with a single dominant contact residue.",
        "tamarind": {
            "interface_confidence": 0.76,
            "predicted_dg_kcal_mol": -9.1,
            "predicted_tm_celsius": 68.4,
            "immunogenicity_risk": 0.24,
        },
        "modelhub": {"model_agreement": 0.71, "epitope_rmsd_angstrom": 2.4},
        "modal": {"retained_score_across_mutations": 0.41, "decoy_discrimination_margin": 0.22},
    },
    {
        "id": "BF-005",
        "cdr": ("GSTFSNSD", "ITSSGSTN", "ANSDYSGSTQDN"),
        "note": "Short, polar CDR3; predicted contact area is small.",
        "tamarind": {
            "interface_confidence": 0.55,
            "predicted_dg_kcal_mol": -6.2,
            "predicted_tm_celsius": 66.0,
            "immunogenicity_risk": 0.27,
        },
        "modelhub": None,
        "modal": None,
    },
    {
        "id": "BF-006",
        "cdr": ("GRIFVLYA", "ILWLGGVI", "AAILVLWFPIVY"),
        "note": "Hydrophobic paratope variant explored for buried-surface gain.",
        "tamarind": {
            "interface_confidence": 0.74,
            "predicted_dg_kcal_mol": -8.9,
            "predicted_tm_celsius": 63.1,
            "immunogenicity_risk": 0.31,
        },
        "modelhub": {"model_agreement": 0.68, "epitope_rmsd_angstrom": 2.9},
        "modal": None,
    },
    {
        "id": "BF-007",
        "cdr": ("GRTFSTYD", "INSGGSRT", "AADSGYNTWSEY"),
        "note": "Framework-stabilised variant with an extended CDR2 contact.",
        "tamarind": {
            "interface_confidence": 0.77,
            "predicted_dg_kcal_mol": -9.8,
            "predicted_tm_celsius": 72.3,
            "immunogenicity_risk": 0.17,
        },
        "modelhub": {"model_agreement": 0.75, "epitope_rmsd_angstrom": 2.1},
        "modal": {"retained_score_across_mutations": 0.69, "decoy_discrimination_margin": 0.28},
    },
    {
        "id": "BF-008",
        "cdr": ("GSTFSSND", "ITWSGSTT", "ATRDGSNSWQDY"),
        "note": "Alternate CDR3 register; two models place the loop differently.",
        "tamarind": {
            "interface_confidence": 0.72,
            "predicted_dg_kcal_mol": -8.4,
            "predicted_tm_celsius": 67.5,
            "immunogenicity_risk": 0.25,
        },
        "modelhub": {"model_agreement": 0.51, "epitope_rmsd_angstrom": 3.4},
        "modal": None,
    },
    {
        "id": "BF-009",
        "cdr": ("GSSFSNTD", "ISSSGDTN", "ANQDGSGSTQDS"),
        "note": "Highly polar paratope; predicted interface is diffuse.",
        "tamarind": {
            "interface_confidence": 0.49,
            "predicted_dg_kcal_mol": -5.1,
            "predicted_tm_celsius": 64.8,
            "immunogenicity_risk": 0.29,
        },
        "modelhub": None,
        "modal": None,
    },
    {
        "id": "BF-010",
        "cdr": ("GRTFSSYD", "ISSGGSTT", "AARDGYSSWTDY"),
        "note": "Strong predicted affinity but a generic, non-selective paratope.",
        "tamarind": {
            "interface_confidence": 0.80,
            "predicted_dg_kcal_mol": -10.0,
            "predicted_tm_celsius": 70.1,
            "immunogenicity_risk": 0.20,
        },
        "modelhub": {"model_agreement": 0.73, "epitope_rmsd_angstrom": 2.2},
        "modal": {"retained_score_across_mutations": 0.62, "decoy_discrimination_margin": 0.09},
    },
    {
        "id": "BF-011",
        "cdr": ("GRTFSLYD", "ISWSGGST", "AAIRGYLSDSDY"),
        "note": "Strong predicted binder carrying a hydrophobic CDR3 apex.",
        "tamarind": {
            "interface_confidence": 0.79,
            "predicted_dg_kcal_mol": -9.9,
            "predicted_tm_celsius": 70.8,
            "immunogenicity_risk": 0.37,
        },
        "modelhub": {"model_agreement": 0.76, "epitope_rmsd_angstrom": 2.0},
        "modal": None,
    },
    {
        "id": "BF-012",
        "cdr": ("GSTFSNYS", "ITSGGSTN", "ANRDYSNSTQDY"),
        "note": "Truncated contact surface; predicted engagement is marginal.",
        "tamarind": {
            "interface_confidence": 0.57,
            "predicted_dg_kcal_mol": -6.9,
            "predicted_tm_celsius": 65.4,
            "immunogenicity_risk": 0.26,
        },
        "modelhub": None,
        "modal": None,
    },
    {
        "id": "BF-013",
        "cdr": ("GRTFSSND", "ISSGGNTT", "ATRDYSGSWNDY"),
        "note": "Models agree on contacts but disagree on loop backbone placement.",
        "tamarind": {
            "interface_confidence": 0.70,
            "predicted_dg_kcal_mol": -8.1,
            "predicted_tm_celsius": 66.9,
            "immunogenicity_risk": 0.28,
        },
        "modelhub": {"model_agreement": 0.61, "epitope_rmsd_angstrom": 4.7},
        "modal": None,
    },
    {
        "id": "BF-014",
        "cdr": ("GRTFSDYD", "IDSGGRTS", "AKDSGYQTRPDY"),
        "note": "Unrelated-antigen binder carried through the pipeline unlabelled.",
        "tamarind": {
            "interface_confidence": 0.31,
            "predicted_dg_kcal_mol": -3.2,
            "predicted_tm_celsius": 73.0,
            "immunogenicity_risk": 0.15,
        },
        "modelhub": None,
        "modal": None,
    },
    {
        "id": "BF-015",
        "cdr": ("YSAGSFRT", "GSTSGSIT", "YSDSRYGATWDA"),
        "note": "CDR residues shuffled within each loop; composition preserved.",
        "tamarind": {
            "interface_confidence": 0.38,
            "predicted_dg_kcal_mol": -4.0,
            "predicted_tm_celsius": 62.5,
            "immunogenicity_risk": 0.30,
        },
        "modelhub": None,
        "modal": None,
    },
    {
        "id": "BF-016",
        "cdr": ("GRTFSSYA", "ISWSGGST", "ADRGASSTGYDY"),
        "note": "Two predicted interface contacts substituted to alanine and glycine.",
        "tamarind": {
            "interface_confidence": 0.52,
            "predicted_dg_kcal_mol": -5.8,
            "predicted_tm_celsius": 74.1,
            "immunogenicity_risk": 0.14,
        },
        "modelhub": None,
        "modal": None,
    },
]

# The redesign. Produced by the redesign step, not present at generation time.
REDESIGN = {
    "id": "BF-017",
    "parent_id": "BF-011",
    "cdr": ("GRTFSSYD", "ISWSGGST", "SASRGYNSWSEY"),
    "note": (
        "Redesign of BF-011. Three hydrophobic CDR apex residues (L, W, L) were "
        "substituted with polar residues (N, S, E) to break the aggregation-prone "
        "patch, and the CDR1/CDR2 loops were reverted to the framework-consensus "
        "loops. Predicted affinity was allowed to degrade in exchange."
    ),
    "tamarind": {
        "interface_confidence": 0.78,
        "predicted_dg_kcal_mol": -9.5,
        "predicted_tm_celsius": 69.4,
        "immunogenicity_risk": 0.28,
    },
    "modelhub": {"model_agreement": 0.74, "epitope_rmsd_angstrom": 2.3},
    "modal": {"retained_score_across_mutations": 0.72, "decoy_discrimination_margin": 0.33},
}

# Ground truth. Written to a separate file; the scoring path never reads it.
CONTROL_LABELS = {
    "BF-001": "positive_control",
    "BF-014": "unrelated_binder_negative",
    "BF-015": "shuffled_cdr_negative",
    "BF-016": "interface_disrupting_mutant",
}

# Epitope-contact positions used by the mutation scan (1-based, on the
# assembled sequence). Chosen as the CDR3 apex plus two CDR2 contacts.
EPITOPE_CONTACT_OFFSETS = [2, 4, 6, 8]


def build_candidate(entry: dict, *, is_redesign: bool = False) -> dict:
    cdr1, cdr2, cdr3 = entry["cdr"]
    sequence, spans = assemble(cdr1, cdr2, cdr3)
    seq_metrics = sequence_metrics(sequence, spans)
    contacts = [spans.cdr3[0] + off for off in EPITOPE_CONTACT_OFFSETS]
    return {
        "id": entry["id"],
        "name": entry["id"],
        "sequence": sequence,
        "format": "nanobody",
        "parent_id": entry.get("parent_id"),
        "generation_note": entry["note"],
        "cdr_spans": {"cdr1": list(spans.cdr1), "cdr2": list(spans.cdr2), "cdr3": list(spans.cdr3)},
        "cdr": {"cdr1": cdr1, "cdr2": cdr2, "cdr3": cdr3},
        "epitope_contact_positions": contacts,
        "sequence_metrics": seq_metrics,
        "tamarind_metrics": entry["tamarind"],
        "model_hub_metrics": entry["modelhub"],
        "modal_metrics": entry["modal"],
        "is_redesign": is_redesign,
    }


THRESHOLDS = {
    "surface_hydrophobicity": ("max", 0.45),
    "aggregation_propensity": ("max", 0.30),
    "net_charge_at_ph7": ("range", (-2.0, 6.0)),
    "unpaired_cysteines": ("max", 0.0),
    "n_glyc_sequons": ("max", 1.0),
}

EXPECTED_DEV_FAILURES = {"BF-006", "BF-011"}


def dev_failures(metrics: dict[str, float], tamarind: dict) -> list[str]:
    failed = []
    for name, rule in THRESHOLDS.items():
        value = metrics[name]
        if rule[0] == "max" and value > rule[1]:
            failed.append(name)
        elif rule[0] == "range" and not (rule[1][0] <= value <= rule[1][1]):
            failed.append(name)
    if tamarind["predicted_tm_celsius"] < 60.0:
        failed.append("predicted_tm_celsius")
    if tamarind["immunogenicity_risk"] > 0.35:
        failed.append("immunogenicity_risk")
    return failed


def verify(candidates: list[dict], redesign: dict) -> None:
    """Fail loudly if the fixture no longer produces the documented narrative."""
    problems: list[str] = []

    bind_fail = [
        c["id"] for c in candidates if c["tamarind_metrics"]["interface_confidence"] < 0.65
    ]
    if len(bind_fail) != 6:
        problems.append(f"expected 6 binding failures, got {len(bind_fail)}: {bind_fail}")

    struct_fail = [
        c["id"]
        for c in candidates
        if c["model_hub_metrics"]
        and (
            c["model_hub_metrics"]["model_agreement"] < 0.60
            or c["model_hub_metrics"]["epitope_rmsd_angstrom"] > 4.0
        )
    ]
    if len(struct_fail) != 3:
        problems.append(f"expected 3 structure failures, got {len(struct_fail)}: {struct_fail}")

    dev_fail = []
    for c in candidates:
        if c["id"] in bind_fail or c["id"] in struct_fail:
            continue
        failures = dev_failures(c["sequence_metrics"], c["tamarind_metrics"])
        if len(failures) > 1:
            dev_fail.append(c["id"])
    if set(dev_fail) != EXPECTED_DEV_FAILURES:
        problems.append(f"expected developability failures {EXPECTED_DEV_FAILURES}, got {dev_fail}")

    robust_pool = [
        c
        for c in candidates
        if c["id"] not in bind_fail and c["id"] not in struct_fail and c["id"] not in dev_fail
    ]
    robust_fail = [
        c["id"]
        for c in robust_pool
        if not c["modal_metrics"]
        or c["modal_metrics"]["retained_score_across_mutations"] < 0.55
        or c["modal_metrics"]["decoy_discrimination_margin"] < 0.15
    ]
    if len(robust_fail) != 2:
        problems.append(f"expected 2 robustness failures, got {len(robust_fail)}: {robust_fail}")

    survivors = [c["id"] for c in robust_pool if c["id"] not in robust_fail]
    if len(survivors) != 3:
        problems.append(f"expected 3 survivors, got {len(survivors)}: {survivors}")

    # Every non-developability-failure candidate must be clean on the sequence
    # metrics, otherwise the gate would fire for the wrong reason.
    for c in candidates:
        failures = dev_failures(c["sequence_metrics"], c["tamarind_metrics"])
        if c["id"] not in EXPECTED_DEV_FAILURES and len(failures) > 1:
            problems.append(f"{c['id']} has unintended developability failures: {failures}")

    # Redesign must pass developability outright and degrade at least one
    # model-derived metric relative to its parent.
    parent = next(c for c in candidates if c["id"] == redesign["parent_id"])
    r_fail = dev_failures(redesign["sequence_metrics"], redesign["tamarind_metrics"])
    if len(r_fail) > 1:
        problems.append(f"redesign still fails developability: {r_fail}")
    if (
        redesign["sequence_metrics"]["aggregation_propensity"]
        >= parent["sequence_metrics"]["aggregation_propensity"]
    ):
        problems.append("redesign did not reduce aggregation propensity")
    degraded = [
        k
        for k in ("interface_confidence", "predicted_tm_celsius")
        if redesign["tamarind_metrics"][k] < parent["tamarind_metrics"][k]
    ]
    if not degraded:
        problems.append("redesign improved every metric — that is not a credible tradeoff")

    if problems:
        print("\nFIXTURE VERIFICATION FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        raise SystemExit(1)


def report(candidates: list[dict], redesign: dict) -> None:
    header = (
        f"{'id':<8}{'hydro':>7}{'aggr':>7}{'chg':>6}{'cys':>5}{'seq':>5}  {'bind':>5}{'agree':>6}"
    )
    print(header)
    print("-" * len(header))
    for c in candidates + [redesign]:
        m = c["sequence_metrics"]
        t = c["tamarind_metrics"]
        mh = c["model_hub_metrics"]
        print(
            f"{c['id']:<8}{m['surface_hydrophobicity']:>7.3f}{m['aggregation_propensity']:>7.3f}"
            f"{m['net_charge_at_ph7']:>6.1f}{int(m['unpaired_cysteines']):>5}"
            f"{int(m['n_glyc_sequons']):>5}  {t['interface_confidence']:>5.2f}"
            f"{(mh['model_agreement'] if mh else float('nan')):>6.2f}"
        )


def main() -> None:
    candidates = [build_candidate(e) for e in SPEC]
    redesign = build_candidate(REDESIGN, is_redesign=True)
    report(candidates, redesign)
    verify(candidates, redesign)

    out_dir = ROOT / "data" / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "target": "VEGF-A",
        "framework": {"fr1": FR1, "fr2": FR2, "fr3": FR3, "fr4": FR4},
        "generated_by": "scripts/build_fixtures.py",
        "sequence_disclaimer": (
            "These are synthetic VHH scaffold sequences with authored CDR loops. They are "
            "not real therapeutic sequences and the 'reference binder' entry is a "
            "surrogate, not a published anti-VEGF antibody sequence."
        ),
        "candidates": candidates,
        "redesign": redesign,
    }
    (out_dir / "vegfa_candidates.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )

    (out_dir / "benchmark_labels.json").write_text(
        json.dumps(
            {
                "description": (
                    "Ground-truth control roles. The scoring pipeline never reads this file; "
                    "only tools/benchmark joins it back in after candidates have been scored. "
                    "tests/unit/test_blinding.py enforces that."
                ),
                "labels": CONTROL_LABELS,
                "expected_positive": ["BF-001"],
                "expected_negative": ["BF-014", "BF-015", "BF-016"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {out_dir / 'vegfa_candidates.json'}")
    print(f"wrote {out_dir / 'benchmark_labels.json'}")


if __name__ == "__main__":
    main()

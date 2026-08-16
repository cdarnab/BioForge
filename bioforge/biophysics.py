"""Sequence-derived developability metrics.

Two kinds of function live here and they are labelled differently everywhere
they surface:

*Exact* calculations (`net_charge_at_ph7`, `unpaired_cysteines`,
`n_glyc_sequons`) are arithmetic over the sequence. They are as correct as the
sequence is.

*Heuristics* (`surface_hydrophobicity`, `aggregation_propensity`) are simple
scale-based summaries built from the published Kyte-Doolittle hydropathy scale.
They are NOT validated developability predictors and must never be presented as
one. They are here so the developability gate operates on the actual sequence
rather than on a lookup table, which makes the redesign step meaningful.

Nothing in this module calls a model or a network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Kyte & Doolittle (1982), J Mol Biol 157:105-132. Higher = more hydrophobic.
KYTE_DOOLITTLE: dict[str, float] = {
    "A": 1.8,
    "R": -4.5,
    "N": -3.5,
    "D": -3.5,
    "C": 2.5,
    "Q": -3.5,
    "E": -3.5,
    "G": -0.4,
    "H": -3.2,
    "I": 4.5,
    "L": 3.8,
    "K": -3.9,
    "M": 1.9,
    "F": 2.8,
    "P": -1.6,
    "S": -0.8,
    "T": -0.7,
    "W": -0.9,
    "Y": -1.3,
    "V": 4.2,
}

KD_MIN, KD_MAX = -4.5, 4.5

# Charged residues at pH 7.0. Histidine is partially protonated (pKa ~6.0).
POSITIVE = {"K": 1.0, "R": 1.0, "H": 0.09}
NEGATIVE = {"D": 1.0, "E": 1.0}

N_GLYC = re.compile(r"N[^P][ST]")

VALID_AA = set(KYTE_DOOLITTLE)


@dataclass(frozen=True)
class CdrSpans:
    """Half-open [start, end) indices of the three CDR loops."""

    cdr1: tuple[int, int]
    cdr2: tuple[int, int]
    cdr3: tuple[int, int]

    def residues(self, sequence: str) -> str:
        return "".join(sequence[a:b] for a, b in (self.cdr1, self.cdr2, self.cdr3))


def validate_sequence(sequence: str) -> None:
    bad = sorted(set(sequence) - VALID_AA)
    if bad:
        raise ValueError(f"sequence contains non-standard residues: {bad}")


def _normalise_kd(value: float) -> float:
    """Map a Kyte-Doolittle value onto 0..1 where 1 is maximally hydrophobic."""
    return (value - KD_MIN) / (KD_MAX - KD_MIN)


def surface_hydrophobicity(sequence: str, spans: CdrSpans) -> float:
    """HEURISTIC. Mean normalised hydropathy across the three CDR loops.

    CDR residues are used as a stand-in for solvent-exposed paratope residues.
    That approximation is the whole reason this is a heuristic: real surface
    hydrophobicity needs a structure and a solvent-accessibility calculation.
    """
    residues = spans.residues(sequence)
    if not residues:
        return 0.0
    mean_kd = sum(KYTE_DOOLITTLE[r] for r in residues) / len(residues)
    return round(_normalise_kd(mean_kd), 4)


def aggregation_propensity(sequence: str, spans: CdrSpans, window: int = 5) -> float:
    """HEURISTIC. Strongest contiguous hydrophobic patch across the CDR loops.

    Aggregation-prone regions are commonly summarised as runs of consecutive
    hydrophobic residues. This returns the maximum windowed mean normalised
    hydropathy, rescaled so that a fully hydrophilic window is 0.
    """
    residues = spans.residues(sequence)
    if len(residues) < window:
        window = max(1, len(residues))
    best = 0.0
    for i in range(0, len(residues) - window + 1):
        chunk = residues[i : i + window]
        mean_kd = sum(KYTE_DOOLITTLE[r] for r in chunk) / window
        best = max(best, _normalise_kd(mean_kd))
    # Rescale: a window at the neutral midpoint (0.5) reads as ~0 propensity.
    return round(max(0.0, (best - 0.5) * 2.0), 4)


def net_charge_at_ph7(sequence: str) -> float:
    """EXACT (given the simple pKa model above)."""
    charge = 0.0
    for residue in sequence:
        charge += POSITIVE.get(residue, 0.0)
        charge -= NEGATIVE.get(residue, 0.0)
    return round(charge, 2)


def unpaired_cysteines(sequence: str) -> int:
    """EXACT count of cysteines beyond the canonical disulfide pair.

    A VHH domain carries one conserved intradomain disulfide (two cysteines).
    Anything above that is an unpaired free thiol risk.
    """
    total = sequence.count("C")
    return max(0, total - 2) if total >= 2 else total


def n_glyc_sequons(sequence: str) -> int:
    """EXACT count of N-X-S/T sequons where X is not proline."""
    return len(N_GLYC.findall(sequence))


def hydrophobic_fraction(sequence: str) -> float:
    """EXACT fraction of residues with positive Kyte-Doolittle hydropathy."""
    if not sequence:
        return 0.0
    n = sum(1 for r in sequence if KYTE_DOOLITTLE[r] > 0)
    return round(n / len(sequence), 4)


def sequence_metrics(sequence: str, spans: CdrSpans) -> dict[str, float]:
    """All sequence-derived developability metrics for one candidate."""
    validate_sequence(sequence)
    return {
        "surface_hydrophobicity": surface_hydrophobicity(sequence, spans),
        "aggregation_propensity": aggregation_propensity(sequence, spans),
        "net_charge_at_ph7": net_charge_at_ph7(sequence),
        "unpaired_cysteines": float(unpaired_cysteines(sequence)),
        "n_glyc_sequons": float(n_glyc_sequons(sequence)),
    }


# Which metrics are exact arithmetic vs. heuristic summaries. Rendered in the UI.
METRIC_KIND: dict[str, str] = {
    "surface_hydrophobicity": "heuristic_sequence_derived",
    "aggregation_propensity": "heuristic_sequence_derived",
    "net_charge_at_ph7": "exact_sequence_derived",
    "unpaired_cysteines": "exact_sequence_derived",
    "n_glyc_sequons": "exact_sequence_derived",
    "interface_confidence": "model_prediction",
    "predicted_dg_kcal_mol": "model_prediction",
    "model_agreement": "model_comparison",
    "epitope_rmsd_angstrom": "model_comparison",
    "predicted_tm_celsius": "model_prediction",
    "immunogenicity_risk": "model_prediction",
    "retained_score_across_mutations": "model_prediction",
    "decoy_discrimination_margin": "model_prediction",
}

"""Modal validator service — parallel adversarial challenge.

Deploy:
    pip install modal
    modal token new                      # once, per machine
    modal deploy services/modal_validator/app.py

`modal deploy` prints the web endpoint URL. Put it in MODAL_VALIDATOR_URL (the
BioForge adapter appends `/challenge`) and restart the API.

What runs here and what does not
--------------------------------
This service performs the parts of the adversarial challenge that are genuinely
mechanical: enumerating the alanine-scan mutants, fanning them out across
containers, and aggregating the results. It calls `score_interface()` for each
variant.

`score_interface()` as shipped is a **deterministic placeholder** built from the
same sequence heuristics the local fixture path uses. It is not a structure
predictor and the response says so in `scoring_backend`. Replace its body with a
real call — your own model, an ESM-family scorer, a docking run — and the rest
of the fan-out, aggregation and provenance plumbing is already correct.

Refusing to fake this is the point: a placeholder that reported itself as a
structure prediction would be exactly the failure mode BioForge exists to catch.
"""

from __future__ import annotations

import os
from typing import Any

import modal

app = modal.App("bioforge-validator")

image = modal.Image.debian_slim(python_version="3.12").pip_install("fastapi[standard]")

# Kyte & Doolittle hydropathy, duplicated here so the container needs no local
# package install. Keep in sync with bioforge/biophysics.py.
KD = {
    "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5,
    "Q": -3.5, "E": -3.5, "G": -0.4, "H": -3.2, "I": 4.5,
    "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8, "P": -1.6,
    "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2,
}

SCORING_BACKEND = "deterministic_placeholder/v1"

DECOY_WEIGHTS = {"PGF": 0.86, "VEGFB": 0.78, "VEGFC": 0.64, "HSA": 0.21}


def score_interface(sequence: str, contact_positions: list[int], antigen: str) -> float:
    """PLACEHOLDER. Replace with a real interface scorer.

    Deterministic in (sequence, contacts, antigen) so repeated runs agree, and
    sensitive to the contact residues so the alanine scan produces a real signal
    rather than noise.
    """
    if not sequence:
        return 0.0
    contacts = [p for p in contact_positions if 0 <= p < len(sequence)]
    if not contacts:
        return 0.0

    # Contact-residue character drives most of the score.
    contact_signal = sum(KD.get(sequence[p], 0.0) for p in contacts) / len(contacts)
    # Whole-chain composition contributes a small, stable background term.
    background = sum(KD.get(residue, 0.0) for residue in sequence) / len(sequence)

    raw = 0.62 + 0.055 * contact_signal - 0.03 * background
    similarity = DECOY_WEIGHTS.get(antigen.upper(), 1.0)
    return round(max(0.0, min(1.0, raw * similarity)), 4)


@app.function(image=image, timeout=600)
def score_variant(payload: dict[str, Any]) -> dict[str, Any]:
    """One container per variant. This is the parallel unit."""
    return {
        "label": payload["label"],
        "antigen": payload["antigen"],
        "score": score_interface(
            payload["sequence"], payload["contact_positions"], payload["antigen"]
        ),
    }


def _build_jobs(sequence: str, contacts: list[int], decoys: list[str]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = [
        {"label": "wild_type", "antigen": "VEGFA", "sequence": sequence,
         "contact_positions": contacts}
    ]
    for position in contacts:
        if position >= len(sequence) or sequence[position] == "A":
            continue
        mutant = sequence[:position] + "A" + sequence[position + 1 :]
        jobs.append(
            {
                "label": f"{sequence[position]}{position + 1}A",
                "antigen": "VEGFA",
                "sequence": mutant,
                "contact_positions": contacts,
            }
        )
    for decoy in decoys:
        jobs.append(
            {"label": f"decoy_{decoy}", "antigen": decoy, "sequence": sequence,
             "contact_positions": contacts}
        )
    return jobs


@app.function(image=image, timeout=900)
@modal.fastapi_endpoint(method="POST", label="bioforge-challenge")
def challenge(payload: dict[str, Any]) -> dict[str, Any]:
    """POST /challenge — the endpoint the BioForge Modal adapter calls."""
    expected = os.environ.get("BIOFORGE_SHARED_SECRET")
    if expected and payload.get("secret") != expected:
        return {"error": "unauthorised"}

    sequence: str = payload["sequence"]
    contacts: list[int] = payload.get("contact_positions", [])
    decoys: list[str] = payload.get("decoys", list(DECOY_WEIGHTS))

    jobs = _build_jobs(sequence, contacts, decoys)
    results = list(score_variant.map(jobs))
    by_label = {r["label"]: r["score"] for r in results}

    wild_type = by_label.get("wild_type", 0.0)
    mutant_scores = [
        score for label, score in by_label.items()
        if label not in ("wild_type",) and not label.startswith("decoy_")
    ]
    decoy_scores = {
        label.removeprefix("decoy_"): score
        for label, score in by_label.items()
        if label.startswith("decoy_")
    }

    retained = (
        round(min(mutant_scores) / wild_type, 4) if mutant_scores and wild_type > 0 else 0.0
    )
    best_decoy = max(decoy_scores.values(), default=0.0)

    return {
        "candidate_id": payload.get("candidate_id"),
        "retained_score_across_mutations": min(1.0, retained),
        "decoy_discrimination_margin": round(max(0.0, wild_type - best_decoy), 4),
        "wild_type_score": wild_type,
        "mutations": [
            {"label": label, "score": score}
            for label, score in sorted(by_label.items())
            if label != "wild_type" and not label.startswith("decoy_")
        ],
        "decoys": [{"id": name, "score": score} for name, score in sorted(decoy_scores.items())],
        "variants_scored": len(jobs),
        "seed": payload.get("seed"),
        "model_version": f"modal/{SCORING_BACKEND}",
        "scoring_backend": SCORING_BACKEND,
        "warning": (
            "score_interface() in this deployment is a deterministic placeholder, not a "
            "structure or binding predictor. Replace it before treating these numbers as "
            "anything other than plumbing output."
        ),
    }


@app.local_entrypoint()
def main() -> None:
    """Smoke-test the fan-out locally: `modal run services/modal_validator/app.py`."""
    demo = (
        "QVQLVESGGGLVQAGGSLRLSCAASGRTFSSYAMGWFRQAPGKEREFVAISWSGGST"
        "RFTISRDNAKNTVYLQMNSLKPEDTAVYYCAAADRGYSSTWYDYWGQGTQVTVSS"
    )
    result = challenge.local(
        {
            "candidate_id": "BF-001",
            "sequence": demo,
            "contact_positions": [90, 92, 94, 96],
            "decoys": list(DECOY_WEIGHTS),
            "seed": 20260815,
        }
    )
    for key in (
        "retained_score_across_mutations",
        "decoy_discrimination_margin",
        "variants_scored",
        "scoring_backend",
    ):
        print(f"{key:>34}: {result[key]}")
    print(f"{'warning':>34}: {result['warning']}")

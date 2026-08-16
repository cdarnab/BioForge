# Scientific limitations

Read this before showing anyone a result from this system.

## The one-sentence version

BioForge Judge produces a **reproducible, computationally prioritised shortlist**
and an experiment-ready handoff. It does not discover binders, it does not
validate anything, and a candidate it recommends has exactly as much experimental
support as one it rejects: none.

---

## 1. Nothing here is an experimental result

Every candidate-level number in this product is a prediction. No molecule in any
run has been expressed, purified, or put in front of an antigen. The words
"validated", "confirmed", "demonstrated" and "measured" do not apply to any
output, and the system prompt for the narrative layer forbids them explicitly.

What the system is actually claiming when it recommends a candidate: *given these
models and these thresholds, this molecule is a better use of a laboratory slot
than the others we generated.* That is a resource-allocation claim, not a
scientific finding.

## 2. The thresholds are uncalibrated

Every number in `data/policy/gates.yaml` is a demonstration threshold. Each metric
has a `source` field; all of them are currently `null`, and the UI and dossier
render `calibrated: no` wherever that is the case.

They were chosen to produce an interpretable triage on the seeded fixture set.
They are not decision boundaries derived from a validated dataset, and moving any
of them changes who passes. Before using this on real programs you would need to
fit each threshold against internal data with known outcomes and record the
provenance of that fit in the `source` field.

The practical consequence: **a candidate that fails by a small margin has not
been shown to be worse than one that passes by a small margin.** The decision
engine flags this — where a metric sits closer to its threshold than the reported
uncertainty, the decision record says the call could flip — but a flag is not a
fix.

## 3. Cross-model agreement is not independent evidence

Gate 2 asks whether a structure predictor from a different model family agrees
with the design path. This catches single-model artifacts, which is genuinely
useful. It does not establish that either model is right.

Modern protein structure predictors are trained on overlapping data — largely the
same PDB. Two such models agreeing tells you the prediction is not an idiosyncrasy
of one architecture. It does not tell you the pose is real. Two models trained on
similar data fail in correlated ways, and this gate is blind to exactly those
failures.

The adapter refuses a same-family comparison outright, because a model agreeing
with itself would be worse than having no gate. But "different family" is a much
weaker guarantee than "independent".

## 4. The developability metrics are two different things wearing one label

Gate 3 mixes three categories, and the UI labels each row:

- **Exact sequence arithmetic** — `net_charge_at_ph7`, `unpaired_cysteines`,
  `n_glyc_sequons`. These are as correct as the sequence is. The pKa model for
  charge is crude (histidine gets a flat 0.09) but the counting is exact.
- **Scale-based heuristics** — `surface_hydrophobicity` and
  `aggregation_propensity`. These summarise Kyte-Doolittle hydropathy over the
  CDR loops. They are **not validated developability predictors**. Real surface
  hydrophobicity needs a structure and a solvent-accessibility calculation;
  using CDR residues as a proxy for exposed residues is an approximation that
  will be wrong for any candidate whose loops pack unusually.
- **Model predictions** — `predicted_tm_celsius` and `immunogenicity_risk`. In
  fixture mode these are authored numbers. `predicted_tm_celsius` is presented
  in degrees Celsius, which reads more physical than it is; treat it as an
  ordinal score with a temperature-shaped unit.

Developability in practice is dominated by things none of these capture:
expression titre, process behaviour, viscosity at formulation concentration,
and chemical liabilities in context rather than in isolation.

## 5. The adversarial gate is predictions challenging predictions

Gate 4 is the product's differentiator and it is still made of model output.

- The **alanine scan** substitutes epitope-contact positions and asks how much
  predicted interface confidence survives. If the scorer is insensitive to those
  positions for reasons unrelated to binding, the scan measures the scorer's
  insensitivity, not the molecule's robustness.
- The **decoy panel** is four antigens (PlGF, VEGF-B, VEGF-C, HSA). Four is a
  small panel, they were chosen by hand, and the decoy scores come from the same
  class of model that produced the on-target score. A model that systematically
  over-scores this whole family will pass a non-selective binder.

A candidate that clears gate 4 has survived a challenge from the same epistemic
system that proposed it. That is better than no challenge and much less than an
experiment.

## 6. The benchmark validates the plumbing, not the science

`make benchmark` reports positive-control rank 1, AUROC 1.0, and top-1 enrichment
17×. Those numbers look excellent and they mean less than they appear to.

The controls are labelled in `data/fixtures/benchmark_labels.json` and the
candidate scores are authored fixture values. The benchmark therefore measures
whether the pipeline recovers a separation that was **built into the fixture** —
that blinding holds, that the gates fire, that ranking works, that the ablations
replay correctly. It does not measure whether the underlying scores are
biophysically meaningful, because in fixture mode they are not scores at all.

The blinding itself is real and worth something: `tests/unit/test_blinding.py`
walks the import graph and fails if any scoring module can see the labels. What
it buys you is confidence that a *live* benchmark would be honestly run.

To get a meaningful number you would need real predictors wired to the adapters
and a retrospective set of antigen–antibody complexes with known outcomes, run
across at least three genuinely stochastic seeds.

## 7. Seeds do nothing in fixture mode

The benchmark runs three seeds and reports identical results, and says why: the
fixture data is seed-invariant by construction. The seed is recorded in every
provenance record so that a stochastic live adapter is reproducible, but running
three seeds against fixtures is not a variance estimate and the harness does not
present it as one.

## 8. The sequences are synthetic

Candidates in the seeded demo are a shared VHH framework scaffold with authored
CDR loops. They are not real therapeutic sequences. The candidate labelled a
"reference-binder surrogate" (BF-001) is **not** a published anti-VEGF antibody
sequence — using a real proprietary sequence and calling it a control would have
been worse than using a surrogate and saying so. `sequence_disclaimer` in the
fixture file states this and a test asserts it is there.

This means the sequence-derived developability numbers are real computations over
fake molecules. The arithmetic is right; the inputs are invented.

## 9. Target-specific caveats for VEGF-A

- **Isoform coverage.** VEGF-A is alternatively spliced (VEGF121, VEGF165,
  VEGF189, others). The selected epitope may not exist on every isoform, and the
  isoform used in an assay determines whether a negative result means anything.
  This is surfaced as contradicting evidence in the Evidence Board and it should
  be resolved before any binding work.
- **Family cross-reactivity.** PlGF, VEGF-B, VEGF-C and VEGF-D share the
  cystine-knot fold. The decoy gate is the system's answer to this and it is a
  prediction; a counter-screen on the same chip is the measurement.
- **Composite epitope.** The receptor-binding determinants sit at the dimer poles
  and are contributed by both protomers. Any single-chain modelling of that
  interface is a simplification.
- **Target engagement is not clinical benefit.** This target has a documented
  history of the two coming apart — the metastatic breast cancer indication for
  bevacizumab was withdrawn in 2011 after confirmatory trials. Nothing in this
  pipeline speaks to efficacy.

## 10. What the system deliberately does not do

- It does not compute an overall "quality score" from a language model. Ranking is
  arithmetic over raw metrics with published weights, and the working is in the
  JSON dossier.
- It does not hide contradicting evidence. The Evidence Board renders
  contradictions first, and the synthesis schema has a required
  `strongest_contradiction` field that cannot be omitted.
- It does not write to a system of record without a named human approving it.
- It does not fall back silently. A configured adapter whose call fails returns
  `mode=fixture` with the exception text attached, and the audit event carries it
  as a warning.
- It does not display model reasoning traces. Rationales are structured:
  hypothesis, evidence, test, result, uncertainty, decision, reversal condition.

## 11. What would have to be true for a recommendation to be wrong

Every recommended candidate carries explicit reversal conditions. In general:

1. A binding assay (SPR/BLI) showing no measurable affinity to VEGF-A165.
2. An experimental structure placing the paratope away from the receptor-binding
   region.
3. Expression or SEC data showing aggregation despite the predicted profile.
4. A counter-screen showing comparable binding to PlGF or VEGF-B.

Any one of these overturns the recommendation. Report them back against the
`reversal_conditions` field in the dossier, which is what that field is for.

## 12. If you are evaluating this system

The right question is not "are the numbers good". In fixture mode the numbers are
authored, so of course they are. The right questions are:

- Can you recompute every verdict from the stored metrics and the policy file?
  (Yes — `rerun_offline()`, and a test asserts the replay is identical.)
- Can you tell, for any number on screen, which tool produced it and in what
  mode? (Yes — provenance is on every row.)
- Does the system say what would change its mind? (Yes — per candidate.)
- Does it tell you when it is guessing? (Yes — `mode=fixture` and
  `PREDICTION` labels, everywhere, including in the report header.)

Those are the properties that would still hold once real predictors are wired in.
The scores are the part you would replace.

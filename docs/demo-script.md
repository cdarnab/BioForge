# Three-minute demo script

## Before you start

```bash
make demo          # builds the UI, serves everything on http://127.0.0.1:8000
```

No credentials needed. Open the page, do **not** press anything yet. Have a
second tab on `http://127.0.0.1:8000/docs` if a judge asks about the API.

Pre-flight (10 seconds, before anyone is watching):

- Header shows `all fixture / 7 integrations` and the amber
  `predictions only — not experimental validation` chip.
- If you have run the demo before, that is fine — each seed creates a new run.

---

## 0:00 — the problem (20s)

> "A team can generate thousands of antibody candidates and afford to test maybe
> three. Pick badly and you have burned six weeks and a lot of protein. Every
> tool in this space ranks candidates by a model score. **Our whole product is
> that we then try to prove our own top candidates wrong before we hand them
> over.**"

Point at the amber chip in the header.

> "And nothing here is ever going to tell you a molecule binds. Everything on
> screen is a prediction, and it is labelled as one on every single row."

## 0:20 — start (20s)

Click **Seed VEGF-A demo**.

> "VEGF-A. Real target, public structures, a known drug class. We are asking for
> a nanobody against the receptor-binding pole."

The timeline animates and the app jumps to the Evidence Board as evidence starts
landing.

> "Seven integrations. Right now all seven are in fixture mode and the UI says so
> — that badge is on every number this thing produces, and it never says 'live'
> for something it didn't actually fetch."

## 0:40 — evidence (25s)

Contradictions render first, in red, above everything else.

> "Twelve cited items. Note the ordering: **contradicting evidence is at the
> top.** The system is not allowed to bury this — the synthesis schema has a
> required field for the strongest contradiction."

Point at the isoform card.

> "This one matters. VEGF-A is alternatively spliced and the epitope we picked
> isn't on every isoform. If you run your assay against the wrong construct, a
> negative result means nothing."

Tap the four stat tiles across the top.

> "And every item is graded: **observed** — that's a crystal structure —
> versus **annotated**, versus **reported**, versus **predicted**. Those are
> different kinds of knowing and we refuse to blur them."

## 1:05 — candidates and the first two gates (25s)

Click **Candidate Court**. Sixteen cards are filling in and gates are resolving
live.

> "Sixteen candidates. Four gates each — the coloured bar on every card."

Point at the funnel on the right as it fills.

> "Gate one, predicted binding: six candidates gone. Gate two is the interesting
> one — **an independent structure model from a different family**. Three more
> candidates die here. The design model liked them; a second opinion didn't. If
> both predictions came from the same model family the adapter refuses to run
> the gate at all, because a model agreeing with itself is worse than no gate."

Click any red card, e.g. **BF-003**.

> "Full audit on every rejection: the metric, the threshold, the tool and model
> version, whether the number was computed from the sequence or predicted, and
> what evidence would reverse the decision."

Close the drawer.

## 1:30 — Challenge Survivors (30s) ← **the moment**

Point at the pulsing red button.

> "Five candidates are still standing and the run has **stopped and is waiting
> for me**. This next step is the product's actual claim, so a person has to
> press it."

Click **⚔ Challenge Survivors**.

> "Alanine scan across every epitope-contact position, plus a decoy panel — PlGF,
> VEGF-B, VEGF-C, albumin. Fanned out in parallel."

Two cards desaturate and go red.

> "**BF-004 collapsed under mutation** — its predicted interface was resting on
> one residue. And **BF-010 binds the decoys about as well as the target.** That
> one had the *third highest predicted affinity in the entire set.* On a
> single-model score it goes straight to the bench and you find out at the SPR
> stage."

*(If asked for proof: `make benchmark` asserts exactly this — there's a test
called `test_single_model_score_would_ship_a_candidate_the_pipeline_rejected`.)*

## 2:00 — redesign (25s)

Click **⟳ Redesign near-miss**.

> "BF-011 missed by the narrowest margin of anything we rejected — a hydrophobic
> patch on the CDR3 apex. We swap three residues for polar ones and re-run **all
> four gates**, not just the one it failed."

BF-017 appears with a violet "redesign" flag and lands at rank 3.

Go to **Decision Dossier** → the redesign delta table.

> "Aggregation propensity 0.29 to 0.07 — and that's computed from the actual
> sequence, not looked up. But look at the rest: predicted affinity down,
> cross-model agreement down, Tm down 1.4 degrees. **We show the tradeoff.** A
> redesign that improved every number at once would mean we were lying, and
> there's a test that fails the build if that ever happens."

## 2:25 — the handoff (25s)

Scroll the Decision Dossier.

> "Three candidates recommended. Each one carries what's still uncertain, what
> would reverse the decision, and the specific wet-lab step to run next."

Point at Downloads.

> "Markdown dossier, JSON with the full audit trail and the policy embedded, a
> CSV with every raw score and its provenance, and a 96-well plate map — with the
> positive control on it, because an all-negative plate without one is
> uninterpretable."

Point at the Benchling card.

> "And to write any of this to Benchling, a human types their name. The adapter
> refuses the write otherwise, and the approval goes in the audit log."

## 2:50 — close (10s)

> "Every threshold in there is in one YAML file and every verdict is recomputable
> from the stored numbers. No language model produced a single score — Claude
> writes the prose, the policy engine makes the decisions."
>
> **"BioForge Judge doesn't just propose molecules. It tries to prove itself
> wrong, and it shows you exactly why a candidate does or doesn't deserve a real
> experiment."**

---

## Likely questions

**"Are any of these numbers real?"**
The sequence-derived developability metrics are genuinely computed on every run —
Kyte-Doolittle hydropathy, exact charge, sequon regex. The model-derived scores
are fixture values in this demo and every one is stamped `fixture`. Wire an
`ANTHROPIC_API_KEY` or a Tamarind endpoint and those rows flip to `live` with the
model version attached.

**"How do I know the benchmark isn't cheating?"**
The control labels live in a separate file that the scoring path cannot import.
`tests/unit/test_blinding.py` walks the import graph and fails the build if any
scoring module references them, and checks the candidate fixture contains no
label strings.

**"What happens when a service goes down?"**
`make test` includes a case that kills a live adapter mid-call. It returns
`mode=fixture` with the exception text attached, the audit event carries it as a
warning, and the UI shows the degraded badge. There is no code path that reports
`live` for data it didn't fetch live.

**"Why should I trust the ranking?"**
You shouldn't trust it — you should recompute it. The weights are in
`data/policy/gates.yaml`, the working is in the JSON dossier per candidate, and
`rerun_offline()` replays any policy over the stored metrics. There's a test
asserting the replay reproduces the live verdicts exactly.

**"Could you just be overfitting to your own fixture?"**
Yes, and that is the honest limitation — see `docs/scientific-limitations.md` §6.
The benchmark validates the plumbing, not the science. What it does establish is
that a *real* benchmark would be honestly run.

---

## Recovery

| Problem | Fix |
|---|---|
| Stream badge says "idle" | Hit ⟳ in the header. State is durable; nothing is lost. |
| Buttons disabled | Wrong phase. Challenge needs `INDEPENDENT_VALIDATION`; redesign needs the challenge done. |
| Want a clean slate | Press **Seed VEGF-A demo** again — new run, old one still in the list. |
| Everything is broken | `make demo-headless` prints the whole narrative to the terminal in ~1 second. |

**Pacing.** `DEMO_PACE_MS=550` in `.env` sets the deliberate step delay. Lower it
to 200 if you talk fast; set it to 0 for a screen recording you'll cut.

# BioForge Judge

**It tries to prove its own candidates wrong before recommending them.**

A biotech team can generate thousands of antibody or nanobody candidates and
afford to test a handful. BioForge Judge takes a protein target, an epitope, and
a target product profile, then gathers cited evidence, writes falsifiable
hypotheses, generates candidates, runs them through four independent gates,
**adversarially challenges the survivors**, redesigns one near-miss, and produces
an auditable, experiment-ready package.

> **Everything this system outputs is a computational prediction.** No candidate
> has been expressed, purified, or tested for binding. The deliverable is a
> reproducible shortlist and a laboratory handoff — not evidence that any
> molecule binds anything. See [docs/scientific-limitations.md](docs/scientific-limitations.md).

---

## Quick start

```bash
make setup      # venv + web deps (needs uv, Node 18+, Python 3.12)
make demo       # builds the UI and serves everything on http://127.0.0.1:8000
```

Open <http://127.0.0.1:8000> and press **Seed VEGF-A demo**.

**No credentials are required.** Every integration runs in deterministic fixture
mode and the UI labels it as such on every number. Nothing is stubbed out or
silently skipped — the workflow, the gates, the audit log, the dossier and the
downloads are all fully exercised.

No browser? `make demo-headless` runs the whole thing in ~1 second and writes
every artifact to `artifacts/demo/`.

<details>
<summary>Setup without <code>make</code></summary>

```bash
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -e ".[dev]"
cd web && npm install && npm run build && cd ..
cp .env.example .env
.venv/bin/python -m uvicorn bioforge.api.main:app --port 8000
```
</details>

---

## What you'll see

Five views, built around the one in the middle.

| View | What it's for |
|---|---|
| **Mission Control** | Target, product profile, per-adapter integration modes, and the live immutable audit trail. |
| **Evidence Board** | Cited evidence with **contradictions rendered first**, graded observed / annotated / reported / predicted. |
| **Hypothesis Ledger** | Each hypothesis with the results that would falsify it, fixed before any gate runs. |
| **Candidate Court** | The centrepiece. Every candidate moving through four gates in real time, with the funnel and the rejection breakdown beside it. |
| **Decision Dossier** | The shortlist, the redesign tradeoff, downloads, and the human-approval gate for Benchling. |

The seeded VEGF-A run produces: **16 candidates → 6 fail binding → 3 fail
independent structure → 2 fail developability → 2 fail the adversarial challenge
→ 3 survive**, plus one redesign of the narrowest miss which re-runs all four
gates and lands at rank 3.

---

## The four gates

| # | Gate | Question | Key threshold |
|---|---|---|---|
| 1 | Predicted binding | Does the design path see an interface at all? | `interface_confidence ≥ 0.65` |
| 2 | Independent structure | Does a **different model family** agree about the pose? | `model_agreement ≥ 0.60` |
| 3 | Developability | Would this survive manufacturing? | ≤ 1 flagged liability of 7 |
| 4 | Robustness & decoys | Does it survive an alanine scan and a decoy panel? | `retained ≥ 0.55`, `decoy margin ≥ 0.15` |

Every threshold lives in [`data/policy/gates.yaml`](data/policy/gates.yaml).
Change a number, re-run, get a different — and fully reproducible — answer.
**All thresholds are uncalibrated demonstration values**; the UI and the dossier
say so on every row that lacks a cited source.

### Three properties worth checking

**A language model never produces a score.** Claude is handed the metrics and the
verdicts the policy already computed, and asked for prose. Ranking is a weighted
sum of normalised raw metrics with published weights, and the JSON dossier
embeds the full working per candidate.

**Provenance is on every number.** Tool, model version, parameters, seed, and
`mode ∈ {live, fixture, import_handoff}`. An adapter whose live call fails
returns `mode=fixture` with the exception text attached — there is no code path
that reports `live` for data it didn't fetch live, and a test asserts it.

**The benchmark is blinded structurally.** Control labels live in a file the
scoring path cannot import; `tests/unit/test_blinding.py` walks the import graph
and fails the build if that ever changes.

---

## Why the extra gates earn their place

```
$ make benchmark

positive-control rank    : 1 of 17
AUROC (pos vs neg)       : 1.0
top-k enrichment         : {'1': 17.0, '3': 5.667, '5': 3.4}

ablations (each policy replayed over the same stored raw metrics):
  full policy                  ['BF-001', 'BF-002', 'BF-017']  (13 rejected)
  without_independent_structure ['BF-001', 'BF-002', 'BF-017']  (10 rejected)
      → 3 candidate(s) the full policy rejected now survive: BF-003, BF-008, BF-013
  without_developability       ['BF-001', 'BF-002', 'BF-017']  (11 rejected)
      → 2 candidate(s) the full policy rejected now survive: BF-006, BF-011
  without_robustness           ['BF-001', 'BF-002', 'BF-017']  (11 rejected)
      → 2 candidate(s) the full policy rejected now survive: BF-004, BF-010

single-model-score baseline (no gates at all — the thing this product beats):
  top-3 by interface_confidence: ['BF-001', 'BF-002', 'BF-010']
      ⚠ BF-010 would have gone to the bench, but the full pipeline rejected it
        at the robustness gate (decoy_discrimination_margin)
```

BF-010 has the third-highest predicted affinity in the set and binds the decoy
panel about as well as the target. Rank on one model's score and it goes to the
lab; the adversarial gate catches it. That is the entire product thesis, and
`tests/benchmark/` asserts it rather than describing it.

**These numbers validate the plumbing, not the science.** In fixture mode the
model-derived scores are authored, so the benchmark measures whether the pipeline
recovers a separation built into the fixture. What it establishes is that a live
benchmark would be honestly run. See
[scientific-limitations.md §6](docs/scientific-limitations.md).

---

## Integrations

All seven implement the same adapter interface: `live`, `fixture`, or
`import_handoff`, with the mode recorded in provenance and rendered in the UI.

| Integration | Role | Live path | Enable with |
|---|---|---|---|
| **Anthropic Claude** | Evidence synthesis, hypothesis updates, decision rationales — **prose only** | Official `anthropic` SDK, structured outputs, adaptive thinking | `pip install anthropic` + `ANTHROPIC_API_KEY` |
| **Paperclip** | Literature, FDA, trials, UniProt, PDB | HTTP to an operator-supplied endpoint | `PAPERCLIP_API_URL` + `PAPERCLIP_API_KEY` |
| **Biomni** | Target biology, homologs, isoforms | **Import handoff** — emits a task prompt, parses the export | `POST /api/investigations/{id}/import/biomni` |
| **Tamarind Bio** | Candidate design, structure, developability | HTTP to an operator-supplied endpoint | `TAMARIND_API_URL` + `TAMARIND_API_KEY` |
| **Benchling Model Hub** | Independent structure check (gate 2) | HTTP, with a same-family independence check | `BENCHLING_MODEL_HUB_URL` + `BENCHLING_API_KEY` |
| **Modal** | Parallel mutation scan and decoy challenge | Deployed endpoint in `services/modal_validator/` | `modal deploy` → `MODAL_VALIDATOR_URL` |
| **Benchling** | System of record | `benchling-sdk`, **blocked behind human approval** | `pip install benchling-sdk` + tenant/key/project |

Two deliberate limits, because inventing an API is worse than admitting you don't
have one:

- **No vendor base URL is hard-coded** for Paperclip or Tamarind, and no request
  schema is guessed. Supply the endpoint your team was issued and provenance
  reads *operator-configured endpoint*.
- **The Benchling live write stops short of a guessed schema.** Registering a
  sequence needs the tenant's own registry and schema IDs. The adapter connects,
  then raises with the exact file and function to complete; the prepared records
  stay available for export.

See [`.env.example`](.env.example) for every variable.

---

## Commands

```bash
make help              # all targets

make demo              # build UI + serve on one port          ← the demo
make demo-headless     # full run, no server, writes artifacts
make dev               # API + Vite with hot reload (two ports)
make benchmark         # blinded benchmark + ablations

make test              # 131 tests, ~2.5s
make check             # lint + typecheck + test + production build
make fixtures          # regenerate fixtures (verifies the demo narrative)
```

---

## Verification

```
$ make check
ruff check      All checks passed
ruff format     58 files already formatted
mypy            Success: no issues found in 26 source files
tsc -b          clean
pytest          131 passed in 2.35s
vite build      built in 0.82s
```

Tests that encode a product claim rather than an implementation detail:

- `test_blinding.py` — the answer key cannot reach the scoring path
- `test_no_score_claims_to_be_live_in_fixture_mode` — one allowed exception, and
  it's the module that genuinely computes in-process
- `test_single_model_score_would_ship_a_candidate_the_pipeline_rejected` — the
  core thesis
- `test_redesign_improves_its_target_without_improving_everything` — fails the
  build if a redesign ever improves everything at once
- `test_failure_does_not_fabricate_results` — a killed adapter leaves no verdict
  behind
- `test_a_run_survives_being_reloaded_from_a_new_store` — durability, which is
  what makes the human-in-the-loop pause meaningful

---

## API

```
POST   /api/investigations                                create
POST   /api/investigations/{id}/start                     run to the pause point
GET    /api/investigations/{id}/events                    SSE progress stream
POST   /api/investigations/{id}/challenge                 ← human-triggered
POST   /api/investigations/{id}/redesign[/{candidate_id}] ← human-triggered
POST   /api/investigations/{id}/finalize
GET    /api/investigations/{id}/{evidence|hypotheses|candidates|audit|dossier}
GET    /api/investigations/{id}/artifacts[/{artifact_id}]
POST   /api/investigations/{id}/request-benchling-write
POST   /api/investigations/{id}/approve-benchling-write   requires a named human
POST   /api/investigations/{id}/import/biomni             import handoff
GET    /api/{health|policy|integrations|workflow}
POST   /api/demo/seed                                     the seeded VEGF-A run
```

Interactive docs at `/docs`.

---

## Workflow

```
CREATED → EVIDENCE_GATHERING → HYPOTHESES_CREATED → CANDIDATES_READY
        → PRIMARY_TESTING → INDEPENDENT_VALIDATION
        ⏸ waits for a human to press Challenge Survivors
        → ADVERSARIAL_CHALLENGE → REDESIGNING (max one iteration)
        → FINAL_REVIEW → PACKAGE_CREATED → COMPLETED

any non-terminal state → NEEDS_REVIEW | FAILED
```

The pause is deliberate. The adversarial gate is the claim the product makes, so
a person invokes it. State is durable, so the pause survives a process restart.

---

## Documentation

- [docs/architecture.md](docs/architecture.md) — how it's built and why
- [docs/demo-script.md](docs/demo-script.md) — the three-minute walkthrough, with
  the likely questions and their answers
- [docs/scientific-limitations.md](docs/scientific-limitations.md) — **read this
  before showing anyone a result**

---

## Stack

Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0, SQLite, SSE ·
React 18, TypeScript, Vite, Tailwind v4, Recharts · pytest, ruff, mypy

Chart colours are validated for colour-vision deficiency; status is never
conveyed by colour alone (failed gates carry a hatch pattern and a text label).

One deviation from the build brief's suggested stack: **Vite instead of
Next.js.** This is a single-page instrument panel over a Python API — no SSR, no
routing, no SEO. Vite builds in under a second and FastAPI serves `web/dist`
directly, so `make demo` is one process on one port. Rationale in
[docs/architecture.md](docs/architecture.md).

---

## Licence and intent

Hackathon project. Generated sequences are research candidates, not medical
advice or therapeutics. The seeded demo uses synthetic VHH scaffolds, not real
therapeutic sequences.

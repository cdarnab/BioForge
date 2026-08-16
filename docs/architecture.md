# Architecture

## The shape of the thing

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Web UI (React + Vite + Tailwind)                                        │
│  Mission Control · Evidence Board · Hypothesis Ledger ·                  │
│  Candidate Court · Decision Dossier                                      │
└───────────────┬──────────────────────────────────────┬───────────────────┘
                │ REST                                 │ SSE
┌───────────────▼──────────────────────────────────────▼───────────────────┐
│  FastAPI  (bioforge/api/main.py)                                         │
└───────────────┬──────────────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────────────────┐
│  WorkflowRunner  (bioforge/engine/workflow.py)                           │
│    · drives the state machine                                            │
│    · calls adapters for RAW NUMBERS ONLY                                 │
│    · hands those numbers to the decision policy                          │
│    · writes an immutable audit event per step                            │
└───┬──────────────┬───────────────┬──────────────┬────────────┬───────────┘
    │              │               │              │            │
┌───▼────┐  ┌──────▼──────┐  ┌─────▼──────┐  ┌────▼─────┐ ┌────▼────────┐
│ state_ │  │ decision_   │  │  audit     │  │packaging │ │  adapters   │
│machine │  │ policy      │  │ + EventBus │  │          │ │  (7)        │
└────────┘  └──────┬──────┘  └────────────┘  └──────────┘ └────┬────────┘
                   │                                            │
          ┌────────▼─────────┐                     ┌────────────▼─────────┐
          │ data/policy/     │                     │ live SDK/HTTP/MCP    │
          │   gates.yaml     │                     │        or            │
          │ (all thresholds) │                     │ data/fixtures/*.json │
          └──────────────────┘                     └──────────────────────┘
                   │
        ┌──────────▼──────────────────────────────────────────┐
        │  SQLite:  runs (mutable blob) · audit_events         │
        │           (append-only) · artifacts                  │
        └──────────────────────────────────────────────────────┘
```

## The three rules the code is organised around

**1. Adapters return numbers. The policy decides.**
An adapter's job is to produce a measurement and say where it came from. It has
no opinion on whether the measurement is good. `decision_policy.py` is the only
module that can set `passed`, and it does so by comparing stored values against
`data/policy/gates.yaml`. That separation is what makes the dossier reproducible
— change a threshold, re-run `rerun_offline()`, get a different answer from the
same measurements.

**2. A language model never produces a score.**
`anthropic_adapter.py` is handed the metrics and the verdicts that the policy has
*already* computed, and asked for prose. Its structured-output schemas contain no
numeric score fields except `posterior_confidence` on a hypothesis, which is a
narrative judgement about a hypothesis, not a candidate gate. If Claude is
unavailable the adapter renders deterministic templates from the same inputs, so
the prose can never drift from the data it describes.

**3. Mode is recorded, never inferred.**
Every result carries a `Provenance` with `mode ∈ {live, fixture, import_handoff,
unavailable}`. An adapter that was configured for live use but whose call failed
must call `self.degraded(reason)`, which returns `mode=fixture` plus the
exception text. There is no code path that returns `mode=live` for data that was
not obtained live, and `tests/integration/test_workflow.py::
test_no_score_claims_to_be_live_in_fixture_mode` asserts it.

## Why these choices

**Vite + React rather than Next.js.** The build brief suggests Next.js. This is a
single-page instrument panel talking to a Python API over REST and SSE — no SSR,
no routing, no SEO, no server components. Vite builds in under a second and
`web/dist` is served directly by FastAPI, so `make demo` is one process on one
port. That was worth more for a three-minute demo than anything Next.js adds
here. Everything else in the suggested stack (FastAPI, Pydantic, SQLAlchemy,
SQLite, SSE, Tailwind, Recharts, pytest) is as specified.

**SQLite with two write disciplines.** `runs` holds the serialised
`Investigation` and is overwritten on every save, so a restarted process resumes
from whatever state it reached. `audit_events` is append-only: `Store` exposes
`append_event` and no update or delete, and re-appending an existing event id
raises. The audit trail's immutability is a property of the storage API rather
than a convention people are asked to respect.

**Durability is what makes the pause meaningful.** The run stops after
`INDEPENDENT_VALIDATION` and waits for a human to press Challenge Survivors. That
only works if the paused state survives — `tests/integration/test_workflow.py::
test_a_run_survives_being_reloaded_from_a_new_store` closes the store, opens a
new one over the same file, and resumes the run.

**An explicit transition table.** `state_machine.py` declares which moves are
legal; `assert_transition` raises `InvalidTransition` listing the allowed set.
Every non-terminal state can reach `NEEDS_REVIEW` and `FAILED`, which is how a
tool failure becomes a visible state rather than an exception that disappears
into a log.

## Data flow for one candidate

```
tamarind.binding_metrics()          → {interface_confidence: 0.79, ...} + Provenance
        │
        ├─ workflow._make_test()    → TestResult (direction/threshold still unset)
        │
        ├─ decision_policy.apply_thresholds()
        │       reads gates.yaml    → sets direction, threshold, passed, rationale
        │
        ├─ decision_policy.evaluate_gate()
        │       counts failures vs max_failed_metrics → GateOutcome
        │
        ├─ decision_policy.evaluate_candidate()
        │       first required failure wins → Decision(reason_codes, uncertainties,
        │                                              reversal_conditions)
        │
        ├─ decision_policy.compute_rank_score()
        │       weighted normalised sum over raw metrics → rank_score + working
        │
        └─ anthropic.decision_rationale()
                given the verdict   → prose only
```

## Gates

| # | Gate | Question it answers | Runs on |
|---|---|---|---|
| 1 | `binding` | Does the design path predict an interface at all? | every candidate |
| 2 | `independent_structure` | Does a *different model family* agree about the pose? | gate-1 survivors |
| 3 | `developability` | Would this molecule survive manufacturing? | gate-1 survivors |
| 4 | `robustness` | Does it survive an alanine scan and a decoy panel? | gates 1–3 survivors |

Gate 2 is only meaningful if the two predictors really differ.
`BenchlingModelHubAdapter._live` compares the reported `model_version` family
against the design path's and raises rather than accept a same-family agreement —
a 0.99 agreement between one model and itself is worse than no gate at all.

Gates 3's metrics come from two different places and are labelled accordingly:
`surface_hydrophobicity`, `aggregation_propensity`, `net_charge_at_ph7`,
`unpaired_cysteines` and `n_glyc_sequons` are computed in-process from the
sequence by `biophysics.py` on every run (`mode=live`, tool
`bioforge.biophysics`); `predicted_tm_celsius` and `immunogenicity_risk` are
model predictions from the adapter. The UI renders the distinction on every row.

## Ranking

Ranking never causes a pass or a fail. It orders candidates that already cleared
every gate, using a weighted sum of min-max normalised raw metrics with the
weights in `gates.yaml`. `compute_rank_score` returns the score *and* its full
working, and the JSON dossier embeds that working per candidate. The
`ranking_working` block plus the policy is enough for a reader to recompute every
number in the report by hand.

## Live progress

`EventBus` fans out to one `asyncio.Queue` per open SSE connection. Publishing
uses `put_nowait` inside `contextlib.suppress(QueueFull)`, so a stalled browser
tab cannot wedge a run — `tests/integration/test_events.py::
test_a_full_queue_never_blocks_the_workflow` floods a queue past its bound and
asserts the publisher still returns.

`Auditor.record()` writes to the store and publishes to the bus in one call, so a
transition cannot appear in the UI without also being durably recorded. Stream
messages are typed: `snapshot`, `investigation`, `evidence`, `hypothesis`,
`candidate`, `audit`.

## Adapters

All seven implement `Adapter`: `configured`, `status()`, and domain methods
returning `(payload, Provenance)`.

| Adapter | Live path | Without credentials |
|---|---|---|
| `anthropic` | official `anthropic` SDK, structured outputs | deterministic templates over the same inputs |
| `paperclip` | official `paperclip` CLI (`search`, `results --save`, protein VFS) | curated fixture bundle with real public citations |
| `biomni` | none claimed | **import handoff**: emits a task prompt, parses the export |
| `tamarind` | HTTP to an operator-supplied `TAMARIND_API_URL` | fixture predictions + genuinely computed sequence metrics |
| `benchling_model_hub` | HTTP, with a same-family independence check | fixture comparison |
| `modal` | deployed `services/modal_validator` endpoint | mutation set enumerated in-process, scores from fixture |
| `benchling` | `benchling-sdk`, blocked behind human approval | prepares records, writes nothing outside the local store |

Paperclip integrates through its official CLI — there is no HTTP adapter and no
invented endpoint. Tamarind has no hard-coded base URL and no guessed request
schema; if your team was issued an endpoint, point the adapter at it and
provenance reads *operator-configured endpoint* rather than claiming a
vendor-documented integration.

## Benchling write path

Two independent gates, because writing to a customer's system of record is not
reversible from here:

1. `POST /approve-benchling-write` requires `confirm: true` and a non-empty
   `approver`, and records a `human_action` audit event.
2. `BenchlingAdapter.write_records` raises `AdapterError` unless it is passed
   `approved=True` — an adapter that can write to a tenant refuses on its own
   rather than trusting its caller.

`_live_write` deliberately stops short of a guessed schema. Registering an amino
acid sequence needs the tenant's own registry and schema IDs, which cannot be
inferred; the adapter connects, then raises with the exact file and function to
complete, and the prepared records remain available for export.

## Layout

```
bioforge/
  models.py            typed contracts for everything
  biophysics.py        sequence-derived metrics (exact vs heuristic, labelled)
  config.py            settings; every value has a working default
  ids.py               deterministic per-run id counters
  store.py             SQLite; append-only audit discipline
  adapters/            base + 7 integrations + fixture loader
  engine/
    state_machine.py   transition table
    decision_policy.py the only module that decides pass/fail
    workflow.py        orchestration
    audit.py           immutable events + SSE bus
    packaging.py       Markdown / JSON / CSV / plate map
  benchmark/harness.py blinded benchmark + ablations
  api/main.py          REST + SSE
data/
  policy/gates.yaml    every threshold in the product
  fixtures/            candidates, evidence, hypotheses, and the blinded labels
services/modal_validator/  deployable Modal app
web/                   Vite + React UI
```

## Testing strategy

131 tests, ~2.5s. The ones that encode a product claim rather than an
implementation detail:

- `test_blinding.py` walks the import graph and fails if any scoring module
  references the answer key, and checks the candidate fixture contains no label
  strings. Blinding is enforced structurally, not promised.
- `test_no_score_claims_to_be_live_in_fixture_mode` allows exactly one live-mode
  tool — `bioforge.biophysics`, which genuinely does compute in-process.
- `test_single_model_score_would_ship_a_candidate_the_pipeline_rejected` asserts
  the product's central claim: that ranking on one model's score alone puts a
  candidate on the bench that the full pipeline catches.
- `test_redesign_improves_its_target_without_improving_everything` fails if the
  redesign improves every metric, because that would mean the scoring is not
  honest.
- `test_failure_does_not_fabricate_results` kills the model-hub adapter mid-run
  and asserts no candidate is left carrying a verdict from a gate that never ran.

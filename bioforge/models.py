"""Typed data contracts for BioForge Judge.

Every object that crosses a module boundary is defined here. Two rules hold
throughout:

1. Nothing that is a *prediction* may be stored in a field that reads as an
   observation. `EvidenceItem.evidence_level` and `TestResult.tool` carry that
   distinction explicitly and the UI renders it.
2. Every score carries the tool, model version, parameters, and seed that
   produced it, plus the mode (live/fixture/import) of the adapter. A score
   without provenance is a bug, not a display problem.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from .ids import new_id


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# --------------------------------------------------------------------------
# Workflow state machine
# --------------------------------------------------------------------------


class WorkflowState(StrEnum):
    CREATED = "CREATED"
    EVIDENCE_GATHERING = "EVIDENCE_GATHERING"
    HYPOTHESES_CREATED = "HYPOTHESES_CREATED"
    CANDIDATES_READY = "CANDIDATES_READY"
    PRIMARY_TESTING = "PRIMARY_TESTING"
    INDEPENDENT_VALIDATION = "INDEPENDENT_VALIDATION"
    ADVERSARIAL_CHALLENGE = "ADVERSARIAL_CHALLENGE"
    REDESIGNING = "REDESIGNING"
    FINAL_REVIEW = "FINAL_REVIEW"
    PACKAGE_CREATED = "PACKAGE_CREATED"
    COMPLETED = "COMPLETED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"


class AdapterMode(StrEnum):
    """How a result was actually produced. Never inferred — always recorded."""

    LIVE = "live"
    FIXTURE = "fixture"
    IMPORT_HANDOFF = "import_handoff"
    UNAVAILABLE = "unavailable"


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


class Provenance(BaseModel):
    """Attached to every score, claim, and artifact."""

    tool: str
    mode: AdapterMode
    model_version: str = "n/a"
    parameters: dict[str, Any] = Field(default_factory=dict)
    random_seed: int | None = None
    retrieved_at: str = Field(default_factory=utcnow)
    # Populated when mode != LIVE, or when a live call failed and we degraded.
    note: str | None = None

    model_config = {"protected_namespaces": ()}


class IntegrationStatus(BaseModel):
    name: str
    mode: AdapterMode
    configured: bool
    reachable: bool | None = None
    detail: str
    # What the operator would need to do to make this live.
    requirement: str | None = None
    last_checked: str = Field(default_factory=utcnow)
    last_error: str | None = None


# --------------------------------------------------------------------------
# Investigation inputs
# --------------------------------------------------------------------------


class Target(BaseModel):
    name: str
    uniprot_id: str | None = None
    pdb_id: str | None = None
    epitope_description: str = ""


class TargetProductProfile(BaseModel):
    format: Literal["nanobody", "scfv", "igg"] = "nanobody"
    max_candidates: int = 20
    max_finalists: int = 3
    constraints: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Evidence
# --------------------------------------------------------------------------


class EvidenceItem(BaseModel):
    id: str = Field(default_factory=lambda: new_id("ev"))
    claim: str
    source_type: Literal["paper", "database", "regulatory", "trial", "benchling", "analysis"]
    source_title: str
    source_url: str | None = None
    citation_locator: str = ""
    support: Literal["supports", "contradicts", "context_only"] = "context_only"
    # The single most important field in the app: it separates what was measured
    # from what a model guessed.
    evidence_level: Literal["observed", "reported", "annotated", "predicted"]
    relevance: float = 0.0
    confidence: float = 0.0
    tool: str = "fixture"
    provenance: Provenance


# --------------------------------------------------------------------------
# Hypotheses
# --------------------------------------------------------------------------


class Hypothesis(BaseModel):
    id: str = Field(default_factory=lambda: new_id("hyp"))
    statement: str
    falsification_criteria: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    contradicting_evidence_ids: list[str] = Field(default_factory=list)
    planned_tests: list[str] = Field(default_factory=list)
    prior_confidence: float = 0.0
    posterior_confidence: float = 0.0
    status: Literal["proposed", "testing", "survives", "rejected", "uncertain"] = "proposed"
    result_summary: str | None = None
    provenance: Provenance | None = None


# --------------------------------------------------------------------------
# Candidates, tests, decisions
# --------------------------------------------------------------------------

GateName = Literal["binding", "independent_structure", "developability", "robustness"]


class TestResult(BaseModel):
    # Tell pytest this is a domain model, not a test class.
    __test__ = False

    id: str = Field(default_factory=lambda: new_id("tr"))
    gate: GateName
    metric: str
    value: float
    unit: str = ""
    threshold: float | None = None
    threshold_high: float | None = None
    direction: Literal["higher_is_better", "lower_is_better", "in_range", "informational"]
    passed: bool | None = None
    tool: str
    model_version: str = "n/a"
    artifact_ids: list[str] = Field(default_factory=list)
    rationale: str = ""
    # Spread of the estimate where the tool reports one. None means the tool did
    # not report uncertainty — which is itself worth surfacing.
    uncertainty: float | None = None
    provenance: Provenance

    model_config = {"protected_namespaces": ()}


class GateOutcome(BaseModel):
    gate: GateName
    passed: bool
    required: bool
    metrics_failed: list[str] = Field(default_factory=list)
    metrics_passed: list[str] = Field(default_factory=list)
    reason: str = ""
    evaluated_at: str = Field(default_factory=utcnow)


class Decision(BaseModel):
    outcome: Literal["reject", "redesign", "advance", "recommend", "pending"] = "pending"
    reason_codes: list[str] = Field(default_factory=list)
    summary: str = ""
    uncertainties: list[str] = Field(default_factory=list)
    reversal_conditions: list[str] = Field(default_factory=list)
    decided_at: str = Field(default_factory=utcnow)
    decided_by: str = "decision_policy"
    policy_version: str = "unknown"


class Candidate(BaseModel):
    id: str
    name: str
    sequence: str
    format: Literal["nanobody", "scfv", "igg"] = "nanobody"
    parent_id: str | None = None
    generation_tool: str = "fixture"
    generation_note: str = ""
    status: Literal["active", "rejected", "survives", "recommended"] = "active"
    tests: list[TestResult] = Field(default_factory=list)
    gates: list[GateOutcome] = Field(default_factory=list)
    decision: Decision = Field(default_factory=Decision)
    # Transparent composite used only for ranking survivors; never invented by
    # an LLM and always recomputable from `tests` + the policy file.
    rank_score: float | None = None
    rank: int | None = None
    provenance: Provenance | None = None

    def gate(self, name: str) -> GateOutcome | None:
        return next((g for g in self.gates if g.gate == name), None)

    def metric(self, name: str) -> TestResult | None:
        return next((t for t in self.tests if t.metric == name), None)


# --------------------------------------------------------------------------
# Artifacts and audit
# --------------------------------------------------------------------------


class Artifact(BaseModel):
    #: Assigned as `{run_id}-art-{n}` by the workflow runner — artifacts share a
    #: table across runs, so a process-local counter would collide.
    id: str = ""
    run_id: str
    kind: Literal[
        "structure",
        "report_md",
        "report_json",
        "csv_scores",
        "csv_plate",
        "task_prompt",
        "import_manifest",
        "benchmark",
        "raw_tool_output",
    ]
    filename: str
    media_type: str = "application/octet-stream"
    size_bytes: int = 0
    created_at: str = Field(default_factory=utcnow)
    provenance: Provenance | None = None
    description: str = ""


class AuditEvent(BaseModel):
    """Append-only. Nothing in the app updates an audit event after write.

    `id` is left blank here and assigned by the store as `{run_id}-evt-{seq}`,
    so it is unique across runs and stable within one.
    """

    id: str = ""
    run_id: str
    seq: int = 0
    timestamp: str = Field(default_factory=utcnow)
    kind: Literal["state_transition", "tool_call", "decision", "human_action", "error", "info"]
    prev_state: WorkflowState | None = None
    next_state: WorkflowState | None = None
    actor: str = "system"
    summary: str = ""
    input_artifact_ids: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str] = Field(default_factory=list)
    tool: str | None = None
    mode: AdapterMode | None = None
    model_version: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    random_seed: int | None = None
    duration_ms: int | None = None
    error: str | None = None
    warning: str | None = None

    model_config = {"protected_namespaces": ()}


# --------------------------------------------------------------------------
# Investigation aggregate
# --------------------------------------------------------------------------


class BenchlingApproval(BaseModel):
    requested: bool = False
    approved: bool = False
    approved_by: str | None = None
    approved_at: str | None = None
    written: bool = False
    write_mode: AdapterMode | None = None
    records: list[dict[str, Any]] = Field(default_factory=list)
    note: str = ""


class Investigation(BaseModel):
    id: str
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)
    target: Target
    target_product_profile: TargetProductProfile = Field(default_factory=TargetProductProfile)
    mode: Literal["fixture", "live"] = "fixture"
    status: WorkflowState = WorkflowState.CREATED
    status_detail: str = ""
    seed: int = 20260815
    policy_version: str = "unknown"

    evidence: list[EvidenceItem] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    integrations: list[IntegrationStatus] = Field(default_factory=list)
    benchling: BenchlingApproval = Field(default_factory=BenchlingApproval)

    challenge_run: bool = False
    redesign_run: bool = False
    redesign_parent_id: str | None = None
    narrative: dict[str, str] = Field(default_factory=dict)
    error: str | None = None

    def candidate(self, cid: str) -> Candidate | None:
        return next((c for c in self.candidates if c.id == cid), None)

    def finalists(self) -> list[Candidate]:
        ranked = [c for c in self.candidates if c.status == "recommended"]
        return sorted(ranked, key=lambda c: c.rank or 999)

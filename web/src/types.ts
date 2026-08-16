export type AdapterMode = "live" | "fixture" | "import_handoff" | "unavailable";

export type GateName =
  | "binding"
  | "independent_structure"
  | "developability"
  | "robustness";

export interface Provenance {
  tool: string;
  mode: AdapterMode;
  model_version: string;
  parameters: Record<string, unknown>;
  random_seed: number | null;
  retrieved_at: string;
  note: string | null;
}

export interface IntegrationStatus {
  name: string;
  mode: AdapterMode;
  configured: boolean;
  detail: string;
  requirement: string | null;
  last_error: string | null;
}

export interface EvidenceItem {
  id: string;
  claim: string;
  source_type: "paper" | "database" | "regulatory" | "trial" | "benchling" | "analysis";
  source_title: string;
  source_url: string | null;
  citation_locator: string;
  support: "supports" | "contradicts" | "context_only";
  evidence_level: "observed" | "reported" | "annotated" | "predicted";
  relevance: number;
  confidence: number;
  tool: string;
  provenance: Provenance;
}

export interface Hypothesis {
  id: string;
  statement: string;
  falsification_criteria: string[];
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  planned_tests: string[];
  prior_confidence: number;
  posterior_confidence: number;
  status: "proposed" | "testing" | "survives" | "rejected" | "uncertain";
  result_summary: string | null;
}

export interface TestResult {
  id: string;
  gate: GateName;
  metric: string;
  value: number;
  unit: string;
  threshold: number | null;
  threshold_high: number | null;
  direction: "higher_is_better" | "lower_is_better" | "in_range" | "informational";
  passed: boolean | null;
  tool: string;
  model_version: string;
  artifact_ids: string[];
  rationale: string;
  uncertainty: number | null;
  provenance: Provenance;
}

export interface GateOutcome {
  gate: GateName;
  passed: boolean;
  required: boolean;
  metrics_failed: string[];
  metrics_passed: string[];
  reason: string;
}

export interface Decision {
  outcome: "reject" | "redesign" | "advance" | "recommend" | "pending";
  reason_codes: string[];
  summary: string;
  uncertainties: string[];
  reversal_conditions: string[];
  policy_version: string;
}

export interface Candidate {
  id: string;
  name: string;
  sequence: string;
  format: string;
  parent_id: string | null;
  generation_tool: string;
  generation_note: string;
  status: "active" | "rejected" | "survives" | "recommended";
  tests: TestResult[];
  gates: GateOutcome[];
  decision: Decision;
  rank_score: number | null;
  rank: number | null;
}

export interface Artifact {
  id: string;
  run_id: string;
  kind: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  description: string;
}

export interface AuditEvent {
  id: string;
  run_id: string;
  seq: number;
  timestamp: string;
  kind: string;
  prev_state: string | null;
  next_state: string | null;
  actor: string;
  summary: string;
  tool: string | null;
  mode: AdapterMode | null;
  model_version: string | null;
  parameters: Record<string, unknown>;
  error: string | null;
  warning: string | null;
}

export interface BenchlingApproval {
  requested: boolean;
  approved: boolean;
  approved_by: string | null;
  approved_at: string | null;
  written: boolean;
  write_mode: AdapterMode | null;
  records: Record<string, unknown>[];
  note: string;
}

export interface Investigation {
  id: string;
  created_at: string;
  updated_at: string;
  target: {
    name: string;
    uniprot_id: string | null;
    pdb_id: string | null;
    epitope_description: string;
  };
  target_product_profile: {
    format: string;
    max_candidates: number;
    max_finalists: number;
    constraints: string[];
  };
  mode: "fixture" | "live";
  status: string;
  status_detail: string;
  seed: number;
  policy_version: string;
  evidence: EvidenceItem[];
  hypotheses: Hypothesis[];
  candidates: Candidate[];
  artifacts: Artifact[];
  integrations: IntegrationStatus[];
  benchling: BenchlingApproval;
  challenge_run: boolean;
  redesign_run: boolean;
  redesign_parent_id: string | null;
  narrative: Record<string, string>;
  error: string | null;
  progress?: number;
}

export interface PolicyMetric {
  name: string;
  label: string;
  direction: string;
  unit: string;
  minimum: number | null;
  maximum: number | null;
  source: string | null;
  note: string;
  calibrated: boolean;
}

export interface PolicyGate {
  name: GateName;
  title: string;
  required: boolean;
  max_failed_metrics: number;
  description: string;
  metrics: PolicyMetric[];
}

export interface Policy {
  version: string;
  label: string;
  ranking_description: string;
  gates: PolicyGate[];
  ranking: {
    metric: string;
    weight: number;
    direction: string;
    floor: number;
    ceiling: number;
  }[];
  reason_codes: Record<string, string>;
}

export const GATE_ORDER: GateName[] = [
  "binding",
  "independent_structure",
  "developability",
  "robustness",
];

export const GATE_LABEL: Record<GateName, string> = {
  binding: "Binding",
  independent_structure: "Independent structure",
  developability: "Developability",
  robustness: "Robustness / decoys",
};

export const METRIC_KIND_LABEL: Record<string, string> = {
  exact_sequence_derived: "computed from sequence",
  heuristic_sequence_derived: "sequence heuristic",
  model_prediction: "model prediction",
  model_comparison: "cross-model comparison",
};

export const METRIC_KIND: Record<string, string> = {
  surface_hydrophobicity: "heuristic_sequence_derived",
  aggregation_propensity: "heuristic_sequence_derived",
  net_charge_at_ph7: "exact_sequence_derived",
  unpaired_cysteines: "exact_sequence_derived",
  n_glyc_sequons: "exact_sequence_derived",
  interface_confidence: "model_prediction",
  predicted_dg_kcal_mol: "model_prediction",
  model_agreement: "model_comparison",
  epitope_rmsd_angstrom: "model_comparison",
  predicted_tm_celsius: "model_prediction",
  immunogenicity_risk: "model_prediction",
  retained_score_across_mutations: "model_prediction",
  decoy_discrimination_margin: "model_prediction",
};

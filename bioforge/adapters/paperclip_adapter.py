"""Paperclip: literature, regulatory, clinical-trial and protein evidence.

Live mode drives the **official `paperclip` CLI** the operator installed. There
is no invented HTTP endpoint in this adapter — the transport is
`bioforge/adapters/paperclip_cli.py`, which shells out to the binary and parses
its documented CSV export and protein VFS.

Two design choices worth calling out:

**It actively searches for disconfirming evidence.** Alongside the topical
queries, the adapter runs an explicit contradiction probe per source — failed
trials, withdrawn indications, cross-reactivity, resistance. A system whose
pitch is adversarial self-correction should not discover its contradictions by
luck, and an evidence set with zero contradictions for a well-studied target is
a retrieval failure rather than good news.

**Partial failure is normal and visible.** Sources are queried concurrently;
each one that times out or errors is recorded in the provenance and surfaced in
the UI as a per-source note. One dead source degrades the evidence base, it does
not fail the run, and it never silently disappears.
"""

from __future__ import annotations

import re
from typing import Any

from ..models import AdapterMode, EvidenceItem, Provenance, Target
from .base import Adapter
from .fixtures import evidence_fixture
from .paperclip_cli import PaperclipCLI, SearchHit, SourceOutcome

# --------------------------------------------------------------------------
# Query planning
# --------------------------------------------------------------------------

#: (paperclip source, purpose, evidence source_type, evidence level, confidence prior)
SOURCE_PROFILE: dict[str, tuple[str, str, float]] = {
    # source_type, evidence_level, confidence prior
    "pmc": ("paper", "reported", 0.70),
    "biorxiv": ("paper", "reported", 0.50),
    "medrxiv": ("paper", "reported", 0.50),
    "fda": ("regulatory", "reported", 0.85),
    "trials/us": ("trial", "reported", 0.60),
    "trials": ("trial", "reported", 0.60),
}

#: Phrases that mark a result as disconfirming. Deliberately conservative — a
#: false "contradicts" is much less harmful than a missed one, because the UI
#: puts contradictions at the top where a human reads them.
CONTRADICTION_PATTERNS = [
    r"\bwithdraw(n|al)\b",
    r"\bterminated\b",
    r"\bdiscontinu(ed|ation)\b",
    r"\bfail(ed|ure|s to meet)\b",
    r"\bdid not (meet|improve|demonstrate|show)\b",
    r"\bno (significant|clinically meaningful|survival) (difference|benefit|improvement)\b",
    r"\bnot (superior|effective)\b",
    r"\black of efficacy\b",
    r"\bcross[- ]react",
    r"\boff[- ]target\b",
    r"\bresistance\b",
    r"\brelapse\b",
    r"\badverse\b",
    r"\btoxicit",
    r"\bimmunogenic",
    r"\baggregat",
    r"\blimitation",
]

#: Phrases that mark a result as supporting the therapeutic hypothesis.
SUPPORT_PATTERNS = [
    r"\bneutraliz",
    r"\binhibit",
    r"\bblock(s|ed|ing)?\b",
    r"\bapproved\b",
    r"\befficacy\b",
    r"\bpotent\b",
    r"\bhigh[- ]affinity\b",
    r"\bcrystal structure\b",
    r"\bco[- ]crystal\b",
    r"\bnanobod",
    r"\bbiosimilar\b",
]

_CONTRADICTION_RE = re.compile("|".join(CONTRADICTION_PATTERNS), re.IGNORECASE)
_SUPPORT_RE = re.compile("|".join(SUPPORT_PATTERNS), re.IGNORECASE)


def classify_support(hit: SearchHit) -> tuple[str, str]:
    """Rule-based support classification. Returns (label, basis).

    This is a keyword heuristic, not a judgement, and it says so in the basis
    string that ends up in provenance. Contradiction wins ties: for a triage
    tool, surfacing a possible problem is the safer error.
    """
    text = f"{hit.title} {hit.abstract}"
    if _CONTRADICTION_RE.search(text):
        return "contradicts", "keyword_heuristic:contradiction"
    if _SUPPORT_RE.search(text):
        return "supports", "keyword_heuristic:support"
    return "context_only", "keyword_heuristic:no_match"


def target_aliases(target: Target, protein: dict[str, Any] | None = None) -> set[str]:
    """Surface forms a result must mention to count as being about this target.

    Broad-recall queries — especially the contradiction probes, which pair the
    target with generic words like "terminated" or "withdrawn" — will happily
    return documents about something else entirely. A registry search for
    "VEGF-A terminated withdrawn trial" returned a smartphone-CBT depression
    trial in testing. Requiring an explicit mention is the cheapest honest fix.
    """
    name = target.name.strip()
    aliases = {name.lower(), name.replace("-", "").lower(), name.replace("-", " ").lower()}
    # "VEGF-A" should also match plain "VEGF"; "IL-6R" should match "IL-6".
    if "-" in name:
        stem = name.rsplit("-", 1)[0].strip().lower()
        if len(stem) >= 3:
            aliases.add(stem)
    if protein:
        for key in ("gene_name", "protein_name", "uniprot_id"):
            value = (protein.get(key) or "").strip().lower()
            if len(value) >= 3:
                aliases.add(value)
    return {alias for alias in aliases if alias}


def mentions_target(hit: SearchHit, aliases: set[str]) -> bool:
    text = f"{hit.title} {hit.abstract}".lower()
    return any(alias in text for alias in aliases)


def build_query_plan(target: Target, limit: int) -> list[tuple[str, str, int]]:
    """(source, query, limit) triples covering the brief's required sources."""
    name = target.name
    epitope = (target.epitope_description or "").strip()
    # Keep the epitope contribution short; long natural-language epitope
    # descriptions dilute the retrieval signal.
    epitope_terms = " ".join(epitope.split()[:8]) if epitope else ""

    return [
        ("pmc", f"{name} antibody nanobody epitope binding {epitope_terms}".strip(), limit),
        ("pmc", f"{name} structure receptor complex", max(2, limit // 2)),
        ("fda", f"{name} antibody approval", max(2, limit // 2)),
        ("trials/us", f"{name} antibody", max(2, limit // 2)),
    ]


def build_contradiction_plan(target: Target, limit: int) -> list[tuple[str, str, int]]:
    """Queries whose whole purpose is to find evidence against the programme."""
    name = target.name
    return [
        ("pmc", f"{name} inhibitor resistance failure limitation cross-reactivity", limit),
        ("fda", f"{name} withdrawn indication failed endpoint", max(2, limit // 2)),
        ("trials/us", f"{name} terminated withdrawn trial", max(2, limit // 2)),
    ]


# --------------------------------------------------------------------------
# Adapter
# --------------------------------------------------------------------------


class PaperclipAdapter(Adapter):
    name = "paperclip"
    purpose = "Cited literature, FDA, clinical-trial, UniProt and PDB evidence."
    requirement = (
        "Install the Paperclip CLI and run `paperclip login` (or set PAPERCLIP_API_KEY "
        "for non-interactive auth). Set PAPERCLIP_ENABLED=false to force fixture mode."
    )

    def __init__(self, settings: Any) -> None:
        super().__init__(settings)
        self.cli = PaperclipCLI(
            binary=settings.paperclip_bin,
            timeout_s=settings.paperclip_timeout_s,
            cache_ttl_s=settings.paperclip_cache_ttl_s,
            api_key=settings.paperclip_api_key,
        )

    # -- capability -------------------------------------------------------

    @property
    def configured(self) -> bool:
        """CLI present and not explicitly disabled.

        Whether it is *authenticated* is a separate question answered by the
        probe, because that requires a subprocess call and `configured` is read
        on every request.
        """
        return bool(self.settings.paperclip_enabled) and self.cli.installed

    def status(self):  # type: ignore[override]
        base = super().status()
        if not self.settings.paperclip_enabled:
            base.detail = (
                "Disabled by PAPERCLIP_ENABLED=false — using deterministic fixture evidence."
            )
            return base
        probe = self.cli._probe  # populated by the last refresh; never blocks here
        if probe is None:
            if self.cli.installed:
                base.detail = (
                    "Paperclip CLI detected. Authentication is verified on first use; "
                    "evidence gathering will report the mode it actually used."
                )
            return base
        base.reachable = probe.reachable
        base.detail = probe.detail
        if probe.available:
            base.mode = AdapterMode.LIVE
            base.detail = (
                f"{probe.detail} Sources: PMC, FDA, ClinicalTrials.gov, UniProt/PDB. "
                f"CLI {probe.version}."
            )
        else:
            base.mode = AdapterMode.FIXTURE
        return base

    async def refresh_status(self):
        """Run the capability probe. Called at startup and by /api/integrations."""
        if self.settings.paperclip_enabled and self.cli.installed:
            await self.cli.probe()
        return self.status()

    # -- evidence ---------------------------------------------------------

    async def gather_evidence(self, target: Target) -> tuple[list[EvidenceItem], Provenance]:
        if not self.configured:
            prov = self._fixture_provenance("Paperclip CLI is not installed.")
            return self._fixture_items(prov), prov

        probe = await self.cli.probe()
        if not probe.available:
            prov = self._fixture_provenance(probe.detail)
            return self._fixture_items(prov), prov

        try:
            return await self._live(target, probe)
        except Exception as exc:  # never let a retrieval bug fail the run
            prov = self.degraded(f"{type(exc).__name__}: {exc}")
            return self._fixture_items(prov), prov

    async def _live(self, target: Target, probe) -> tuple[list[EvidenceItem], Provenance]:
        limit = int(self.settings.paperclip_max_results)
        topical = build_query_plan(target, limit)
        adversarial = build_contradiction_plan(target, max(2, limit // 2))

        outcomes = await self.cli.search_many(
            topical + adversarial, timeout_s=self.settings.paperclip_timeout_s
        )
        protein = await self.cli.protein_meta(target.uniprot_id) if target.uniprot_id else None

        version = f"paperclip/{probe.version or 'unknown'}"
        base_parameters = {
            "account": probe.account,
            "server": probe.server,
            "queries": [
                {"source": source, "query": query, "limit": n}
                for source, query, n in topical + adversarial
            ],
            "contradiction_probe_queries": len(adversarial),
        }

        errors = {f"{o.source}: {o.query[:60]}": o.error for o in outcomes if o.error}
        cache_hits = sum(1 for o in outcomes if o.cache_hit)

        note_parts = [
            "Retrieved live through the official Paperclip CLI.",
            f"{len(adversarial)} of {len(outcomes)} queries were contradiction probes.",
        ]
        if cache_hits:
            note_parts.append(f"{cache_hits} query result(s) served from the local cache.")
        if errors:
            note_parts.append(
                f"{len(errors)} source query(ies) failed and contributed no evidence: "
                + "; ".join(f"{k} — {v}" for k, v in list(errors.items())[:4])
            )
        if target.uniprot_id and protein is None:
            note_parts.append(
                f"UniProt lookup for {target.uniprot_id} returned nothing; no database "
                "annotation was added."
            )

        prov = self.provenance(
            mode=AdapterMode.LIVE,
            model_version=version,
            parameters={**base_parameters, "failed_queries": errors, "cache_hits": cache_hits},
            note=" ".join(note_parts),
        )

        items: list[EvidenceItem] = []
        if protein:
            items.append(self._protein_item(protein, target, prov))

        aliases = target_aliases(target, protein)
        seen: set[str] = set()
        off_topic = 0
        adversarial_queries = {query for _, query, _ in adversarial}
        for outcome in outcomes:
            is_probe = outcome.query in adversarial_queries
            for hit in outcome.hits:
                if not hit.doc_id or hit.doc_id in seen or not hit.title:
                    continue
                seen.add(hit.doc_id)
                if not mentions_target(hit, aliases):
                    # Retrieved, but not about this target. Dropping it beats
                    # putting an unrelated trial on the Evidence Board.
                    off_topic += 1
                    continue
                item = self._hit_item(hit, outcome, prov, from_contradiction_probe=is_probe)
                if item is not None:
                    items.append(item)

        if off_topic:
            prov.parameters["filtered_off_topic"] = off_topic
            prov.parameters["target_aliases"] = sorted(aliases)
            prov.note = (
                f"{prov.note} {off_topic} retrieved result(s) were dropped for not mentioning "
                f"the target ({', '.join(sorted(aliases))})."
            )

        if not items:
            raise RuntimeError("every Paperclip query returned nothing on-topic")

        items.append(self._scope_item(prov))
        return items, prov

    # -- item builders -----------------------------------------------------

    def _hit_item(
        self,
        hit: SearchHit,
        outcome: SourceOutcome,
        prov: Provenance,
        *,
        from_contradiction_probe: bool,
    ) -> EvidenceItem | None:
        source_type, evidence_level, confidence = SOURCE_PROFILE.get(
            outcome.source, ("paper", "reported", 0.5)
        )
        support, basis = classify_support(hit)

        claim = hit.abstract.strip() or hit.title.strip()
        if len(claim) > 480:
            claim = claim[:477].rsplit(" ", 1)[0] + "…"

        # Rank-derived, and described as such. This is retrieval position, not a
        # judgement about how relevant the claim actually is.
        relevance = round(max(0.35, 1.0 - 0.06 * (hit.rank - 1)), 2)

        item_prov = prov.model_copy(
            update={
                "parameters": {
                    "paperclip_source": outcome.source,
                    "query": outcome.query,
                    "rank": hit.rank,
                    "doc_id": hit.doc_id,
                    "from_contradiction_probe": from_contradiction_probe,
                    "support_basis": basis,
                    "relevance_basis": "search_rank_position",
                    "confidence_basis": "source_tier_prior_not_claim_judgement",
                    "cache_hit": outcome.cache_hit,
                },
                "note": (
                    "Live Paperclip result. `support` is a keyword heuristic over the title "
                    "and abstract, not a read of the paper; `relevance` is retrieval rank and "
                    "`confidence` is a source-tier prior. None of the three is a judgement "
                    "about whether the claim is true."
                ),
            }
        )

        locator = hit.doc_id
        if hit.date:
            locator = f"{hit.doc_id} · {hit.date}"

        return EvidenceItem(
            claim=claim,
            source_type=source_type,  # type: ignore[arg-type]
            source_title=hit.title or hit.doc_id,
            source_url=hit.best_url(),
            citation_locator=locator,
            support=support,  # type: ignore[arg-type]
            evidence_level=evidence_level,  # type: ignore[arg-type]
            relevance=relevance,
            confidence=confidence,
            tool=self.name,
            provenance=item_prov,
        )

    def _protein_item(
        self, payload: dict[str, Any], target: Target, prov: Provenance
    ) -> EvidenceItem:
        accession = payload.get("accession", target.uniprot_id or "")
        name = payload.get("protein_name") or target.name
        organism = payload.get("organism", "")
        length = payload.get("sequence_length")
        weight = payload.get("mol_weight")
        entry_type = payload.get("entry_type", "")

        details = [f"{name} ({payload.get('gene_name', '')}) from {organism}".strip()]
        if length:
            details.append(f"{length} aa")
        if weight:
            details.append(f"{weight} Da")
        if entry_type:
            details.append(entry_type)

        item_prov = prov.model_copy(
            update={
                "parameters": {
                    "vfs_path": f"/proteins/{accession}/meta.json",
                    "accession": accession,
                    "annotation_score": payload.get("annotation_score"),
                    "confidence_basis": "curated_database_entry",
                },
                "note": (
                    "Read directly from the Paperclip protein VFS. This is a curated database "
                    "annotation — a record of what UniProt asserts, not an observation made "
                    "by this run."
                ),
            }
        )

        return EvidenceItem(
            claim=(
                f"{', '.join(details)}. Reviewed UniProt entry used as the reference sequence "
                "and annotation source for this target."
            ),
            source_type="database",
            source_title=f"UniProtKB {accession} ({payload.get('uniprot_id', '')})",
            source_url=f"https://www.uniprot.org/uniprotkb/{accession}/entry",
            citation_locator=f"{accession} · annotation score {payload.get('annotation_score')}",
            support="context_only",
            evidence_level="annotated",
            relevance=0.95,
            confidence=0.92,
            tool=self.name,
            provenance=item_prov,
        )

    def _scope_item(self, prov: Provenance) -> EvidenceItem:
        """The standing caveat, carried as evidence so it reaches the dossier."""
        return EvidenceItem(
            claim=(
                "No experimental binding, expression, or stability data exists for any "
                "candidate in this run. Every candidate-level number is a computational "
                "prediction."
            ),
            source_type="analysis",
            source_title="BioForge Judge run scope",
            source_url=None,
            citation_locator="This investigation",
            support="contradicts",
            evidence_level="predicted",
            relevance=1.0,
            confidence=1.0,
            tool="bioforge",
            provenance=prov.model_copy(
                update={
                    "tool": "bioforge",
                    "note": "Standing scope statement, not a retrieved document.",
                }
            ),
        )

    # -- fixture ----------------------------------------------------------

    def _fixture_provenance(self, reason: str) -> Provenance:
        return self.provenance(
            mode=AdapterMode.FIXTURE,
            parameters={"bundle": "vegfa_evidence.json", "reason": reason},
            note=(
                f"{reason} Serving the curated fixture bundle: the citations are real public "
                "records but were assembled by hand, not retrieved by a live query."
            ),
        )

    def _fixture_items(self, prov: Provenance) -> list[EvidenceItem]:
        payload = evidence_fixture()
        items: list[EvidenceItem] = []
        for raw in payload["items"]:
            item_prov = prov.model_copy(update={"tool": raw.get("tool", self.name)})
            items.append(EvidenceItem(**raw, provenance=item_prov))
        return items

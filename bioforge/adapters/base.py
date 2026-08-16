"""Shared adapter contract.

Every integration implements the same three things:

* `configured` — are the credentials this adapter needs actually present?
* `status()`   — an `IntegrationStatus` the UI renders in the integration rail.
* domain methods that return `(payload, Provenance)`.

The `Provenance` is the load-bearing part. An adapter that fell back to fixture
data returns `mode=FIXTURE` with a `note` explaining why. It is never allowed to
return `mode=LIVE` for data it did not obtain live — `degraded()` exists so that
the fallback path is one obvious call rather than something each adapter
reinvents.
"""

from __future__ import annotations

import abc
from typing import Any

from ..models import AdapterMode, IntegrationStatus, Provenance


class AdapterError(RuntimeError):
    """Raised when a live call fails. Callers decide whether to degrade or fail."""


class Adapter(abc.ABC):
    #: Stable identifier used in provenance records and audit events.
    name: str = "adapter"
    #: Human-readable purpose, shown in the UI.
    purpose: str = ""
    #: What an operator must supply to make this adapter live.
    requirement: str = ""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._last_error: str | None = None

    # -- capability -------------------------------------------------------

    @property
    @abc.abstractmethod
    def configured(self) -> bool:
        """True when every credential/endpoint this adapter needs is present."""

    @property
    def live_supported(self) -> bool:
        """False for adapters that have no automated interface at all."""
        return True

    def effective_mode(self) -> AdapterMode:
        if not self.live_supported:
            return AdapterMode.IMPORT_HANDOFF
        return AdapterMode.LIVE if self.configured else AdapterMode.FIXTURE

    # -- reporting --------------------------------------------------------

    def status(self) -> IntegrationStatus:
        mode = self.effective_mode()
        if mode is AdapterMode.LIVE:
            detail = f"Credentials present. {self.purpose}"
        elif mode is AdapterMode.IMPORT_HANDOFF:
            detail = (
                f"No automated interface configured. {self.purpose} "
                "Runs as a documented import handoff."
            )
        else:
            detail = f"Not configured — using deterministic fixture data. {self.purpose}"
        return IntegrationStatus(
            name=self.name,
            mode=mode,
            configured=self.configured,
            detail=detail,
            requirement=self.requirement,
            last_error=self._last_error,
        )

    # -- provenance helpers ----------------------------------------------

    def provenance(
        self,
        *,
        mode: AdapterMode | None = None,
        model_version: str = "n/a",
        parameters: dict[str, Any] | None = None,
        seed: int | None = None,
        note: str | None = None,
    ) -> Provenance:
        return Provenance(
            tool=self.name,
            mode=mode or self.effective_mode(),
            model_version=model_version,
            parameters=parameters or {},
            random_seed=seed,
            note=note,
        )

    def degraded(self, reason: str, *, model_version: str = "n/a") -> Provenance:
        """Provenance for a result that fell back to fixture data after a failure.

        Calling this is the only sanctioned way to serve fixture data from an
        adapter that was configured for live use.
        """
        self._last_error = reason
        return Provenance(
            tool=self.name,
            mode=AdapterMode.FIXTURE,
            model_version=model_version,
            note=f"Live call failed, served deterministic fixture instead: {reason}",
        )

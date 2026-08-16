"""One place that knows about every adapter."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from ..config import settings as default_settings
from ..models import IntegrationStatus
from .anthropic_adapter import AnthropicAdapter
from .base import Adapter
from .benchling_adapter import BenchlingAdapter, BenchlingModelHubAdapter
from .biomni_adapter import BiomniAdapter
from .modal_adapter import ModalAdapter
from .paperclip_adapter import PaperclipAdapter
from .tamarind_adapter import TamarindAdapter


@dataclass
class AdapterRegistry:
    anthropic: AnthropicAdapter
    paperclip: PaperclipAdapter
    biomni: BiomniAdapter
    tamarind: TamarindAdapter
    model_hub: BenchlingModelHubAdapter
    modal: ModalAdapter
    benchling: BenchlingAdapter

    @classmethod
    def build(cls, settings: Settings | None = None) -> AdapterRegistry:
        s = settings or default_settings
        return cls(
            anthropic=AnthropicAdapter(s),
            paperclip=PaperclipAdapter(s),
            biomni=BiomniAdapter(s),
            tamarind=TamarindAdapter(s),
            model_hub=BenchlingModelHubAdapter(s),
            modal=ModalAdapter(s),
            benchling=BenchlingAdapter(s),
        )

    def all(self) -> list[Adapter]:
        return [
            self.anthropic,
            self.paperclip,
            self.biomni,
            self.tamarind,
            self.model_hub,
            self.modal,
            self.benchling,
        ]

    def statuses(self) -> list[IntegrationStatus]:
        """Cheap, synchronous snapshot. Never performs I/O."""
        return [adapter.status() for adapter in self.all()]

    async def refresh_statuses(self) -> list[IntegrationStatus]:
        """Re-probe adapters that can actually check their own connectivity.

        Separate from `statuses()` because probing shells out or hits a network,
        and `statuses()` is read on the request path.
        """
        import asyncio

        probes = [
            adapter.refresh_status() for adapter in self.all() if hasattr(adapter, "refresh_status")
        ]
        if probes:
            await asyncio.gather(*probes, return_exceptions=True)
        return self.statuses()

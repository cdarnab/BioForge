"""Runtime configuration. Every value has a working default so the app boots
with an empty environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional dependency; absence must not break boot
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - trivial fallback
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
FIXTURE_DIR = DATA_DIR / "fixtures"
POLICY_DIR = DATA_DIR / "policy"
IMPORT_DIR = Path(os.getenv("BIOMNI_IMPORT_DIR", str(DATA_DIR / "imports")))


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class Settings:
    app_mode: str = field(default_factory=lambda: os.getenv("APP_MODE", "fixture").lower())
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./bioforge.db")
    )
    artifact_dir: Path = field(
        default_factory=lambda: Path(os.getenv("ARTIFACT_DIR", str(ROOT / "artifacts")))
    )
    demo_pace_ms: int = field(default_factory=lambda: _int("DEMO_PACE_MS", 550))
    random_seed: int = field(default_factory=lambda: _int("RANDOM_SEED", 20260815))

    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    anthropic_model: str = field(
        default_factory=lambda: os.getenv("ANTHROPIC_MODEL", "claude-opus-5") or "claude-opus-5"
    )

    paperclip_api_key: str = field(default_factory=lambda: os.getenv("PAPERCLIP_API_KEY", ""))
    paperclip_api_url: str = field(default_factory=lambda: os.getenv("PAPERCLIP_API_URL", ""))

    tamarind_api_key: str = field(default_factory=lambda: os.getenv("TAMARIND_API_KEY", ""))
    tamarind_api_url: str = field(default_factory=lambda: os.getenv("TAMARIND_API_URL", ""))

    benchling_tenant: str = field(default_factory=lambda: os.getenv("BENCHLING_TENANT", ""))
    benchling_api_key: str = field(default_factory=lambda: os.getenv("BENCHLING_API_KEY", ""))
    benchling_project_id: str = field(default_factory=lambda: os.getenv("BENCHLING_PROJECT_ID", ""))
    benchling_mcp_url: str = field(default_factory=lambda: os.getenv("BENCHLING_MCP_URL", ""))
    benchling_model_hub_url: str = field(
        default_factory=lambda: os.getenv("BENCHLING_MODEL_HUB_URL", "")
    )

    modal_validator_url: str = field(default_factory=lambda: os.getenv("MODAL_VALIDATOR_URL", ""))
    modal_token_id: str = field(default_factory=lambda: os.getenv("MODAL_TOKEN_ID", ""))
    modal_token_secret: str = field(default_factory=lambda: os.getenv("MODAL_TOKEN_SECRET", ""))

    def __post_init__(self) -> None:
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        IMPORT_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()

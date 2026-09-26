"""What the catalog knows about one model."""

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class Verification:
    """Results of our own probes. Dates are ISO days; None = never checked."""

    chat_ok: Optional[bool] = None
    chat_checked: Optional[str] = None
    web_search_ok: Optional[bool] = None
    web_search_checked: Optional[str] = None
    error: Optional[str] = None


@dataclass
class CatalogEntry:
    id: str
    provider: str  # "openai" | "anthropic" | "google"
    display_name: str
    released: Optional[str] = None  # ISO date the provider published it
    input_limit: Optional[int] = None
    output_limit: Optional[int] = None
    # "listed": the provider's API lists it. "unlisted": it was listed before
    # and no longer is (kept so old references still resolve).
    status: str = "listed"
    shutdown_date: Optional[str] = None
    capabilities: dict[str, Any] = field(default_factory=dict)
    verification: Verification = field(default_factory=Verification)
    # Where each non-obvious fact came from, e.g. {"input_limit": "override: <url>"}.
    sources: dict[str, str] = field(default_factory=dict)

    @property
    def usable(self) -> bool:
        return self.status == "listed" and bool(self.verification.chat_ok)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CatalogEntry":
        d = dict(d)
        d["verification"] = Verification(**(d.get("verification") or {}))
        return cls(**d)

    def facts(self) -> dict[str, Any]:
        """The provider-reported facts, for change detection."""
        return {
            "display_name": self.display_name,
            "released": self.released,
            "input_limit": self.input_limit,
            "output_limit": self.output_limit,
            "shutdown_date": self.shutdown_date,
            "capabilities": self.capabilities,
        }

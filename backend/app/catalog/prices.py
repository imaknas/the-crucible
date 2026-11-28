"""What calling a model costs, from the hand-maintained price list.

No provider API exposes prices, so data/prices.json is kept by hand from the
providers' pricing pages (each entry names its page). Prices can change on a
known date (introductory prices), so a lookup takes the day it is for.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from app.catalog.names import listed_id
from app.catalog.store import DATA

DEFAULT_PRICES = DATA / "prices.json"


@dataclass(frozen=True)
class Price:
    """USD per 1M tokens."""

    input: float
    output: float
    # Cache-hit price; None = the provider lists none (billed as input).
    cached_input: Optional[float] = None
    # Price of writing a cache entry, where the provider charges for it
    # (Anthropic: 1.25x input for the 5-minute entries the app writes);
    # None = writes are billed as input (OpenAI, Google, xAI).
    cache_write: Optional[float] = None

    def cost(self, input_tokens: int, output_tokens: int, cached_tokens: int = 0,
             written_tokens: int = 0) -> float:
        """`input_tokens` includes cached and written ones, as LangChain reports it."""
        cached = min(cached_tokens, input_tokens) if self.cached_input is not None else 0
        written = min(written_tokens, input_tokens - cached) if self.cache_write is not None else 0
        return (
            (input_tokens - cached - written) * self.input
            + cached * (self.cached_input or 0.0)
            + written * (self.cache_write or 0.0)
            + output_tokens * self.output
        ) / 1_000_000


@dataclass(frozen=True)
class ModelPrice:
    current: Price
    source: str
    # Last day `current` applies; `after` applies from the next day.
    until: Optional[str] = None
    after: Optional[Price] = None
    note: str = ""

    def on(self, day: str) -> Price:
        if self.until and self.after and day > self.until:
            return self.after
        return self.current


def _price(d: Mapping[str, Any]) -> Price:
    return Price(input=d["input"], output=d["output"], cached_input=d.get("cached_input"),
                 cache_write=d.get("cache_write"))


def load_prices(path: Path = DEFAULT_PRICES) -> dict[str, ModelPrice]:
    data = json.loads(path.read_text())
    sources = data.get("sources", {})
    out = {}
    for model_id, d in data["models"].items():
        if d.get("source") not in sources:
            raise ValueError(f"price for {model_id} has no known source")
        out[model_id] = ModelPrice(
            current=_price(d),
            source=sources[d["source"]],
            until=d.get("until"),
            after=_price(d["after"]) if d.get("after") else None,
            note=d.get("note", ""),
        )
    return out


# langchain-anthropic reports cache writes as `cache_creation`, or split by
# lifetime (and `cache_creation` then 0): the 5-minute and 1-hour entries.
WRITE_KEYS = ("cache_creation", "ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")


def written_tokens(details: Mapping[str, Any]) -> int:
    """Input tokens written to the provider's cache, from usage_metadata's input_token_details."""
    return sum(details.get(k) or 0 for k in WRITE_KEYS)


class PriceBook:
    """Prices by model id as of one day.

    Providers report the model that answered by a dated snapshot name
    ("gpt-5.4-nano-2026-03-17"); such names resolve to the longest listed id
    they extend.
    """

    def __init__(self, prices: Mapping[str, ModelPrice], day: str):
        self._prices = dict(prices)
        self.day = day

    def resolve(self, model_name: str) -> Optional[str]:
        return listed_id(model_name, self._prices)

    def price(self, model_name: str) -> Optional[Price]:
        model_id = self.resolve(model_name)
        return self._prices[model_id].on(self.day) if model_id else None

    def cost(self, model_name: str, usage: Mapping[str, Any]) -> Optional[float]:
        """Cost of a LangChain usage_metadata dict; None if the model is unpriced."""
        price = self.price(model_name)
        if price is None:
            return None
        details = usage.get("input_token_details") or {}
        cached = details.get("cache_read", 0) or 0
        return price.cost(usage.get("input_tokens", 0), usage.get("output_tokens", 0), cached,
                          written_tokens(details))

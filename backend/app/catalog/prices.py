"""What calling a model costs, from the hand-maintained price list.

No provider API exposes prices, so data/prices.json is kept by hand from the
providers' pricing pages (each entry names its page). Prices can change on a
known date (introductory prices), so a lookup takes the day it is for.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from app.catalog.store import DATA

DEFAULT_PRICES = DATA / "prices.json"


@dataclass(frozen=True)
class Price:
    """USD per 1M tokens."""

    input: float
    output: float
    # Cache-hit price; None = the provider lists none (billed as input).
    cached_input: Optional[float] = None

    def cost(self, input_tokens: int, output_tokens: int, cached_tokens: int = 0) -> float:
        """`input_tokens` includes cached ones, as LangChain reports it."""
        cached = min(cached_tokens, input_tokens) if self.cached_input is not None else 0
        return (
            (input_tokens - cached) * self.input
            + cached * (self.cached_input or 0.0)
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
    return Price(input=d["input"], output=d["output"], cached_input=d.get("cached_input"))


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
        name = model_name.strip().lower().removeprefix("models/")
        if name in self._prices:
            return name
        matches = [m for m in self._prices if name.startswith(m + "-")]
        return max(matches, key=len) if matches else None

    def price(self, model_name: str) -> Optional[Price]:
        model_id = self.resolve(model_name)
        return self._prices[model_id].on(self.day) if model_id else None

    def cost(self, model_name: str, usage: Mapping[str, Any]) -> Optional[float]:
        """Cost of a LangChain usage_metadata dict; None if the model is unpriced."""
        price = self.price(model_name)
        if price is None:
            return None
        cached = (usage.get("input_token_details") or {}).get("cache_read", 0) or 0
        return price.cost(usage.get("input_tokens", 0), usage.get("output_tokens", 0), cached)
